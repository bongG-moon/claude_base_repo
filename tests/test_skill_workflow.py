from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.skill_registry import inventory_skills, set_skill_preference
from company_agent.skill_catalog import refresh_skill_catalog
from company_agent.skill_workflow import prepare, observe, _preparation_advice as preflight, select
from company_agent.state import begin_turn, load_session, record_activity
from company_agent.cli import main as cli_main


class SkillWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state, self.project, self.plugin, self.claude = [self.root / x for x in ("state", "한글 project", "plugin", "claude")]
        self.project.mkdir()
        self.sid = "workflow-test"
        self.env = patch.dict(os.environ, {"COMPANY_AGENT_USER_STATE": str(self.state),
            "CLAUDE_CONFIG_DIR": str(self.claude), "COMPANY_AGENT_KNOWLEDGE_BASE": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        atomic_write_json(self.plugin / ".claude-plugin/plugin.json", {"name": "company-agent", "version": "test"})
        self.reader = self.skill(self.plugin / "skills/fixture-reader", "fixture-reader", "Read existing PowerPoint slides")
        self.deck = self.skill(self.plugin / "skills/presentation", "presentation", "Create slide decks")
        self.options = {"project_root": self.project, "plugin_root": self.plugin, "claude_root": self.claude}
        self.turn = begin_turn(self.sid, "MEDIUM", False, [], self.state)["turnId"]
        self.refresh()

    def skill(self, directory, name, description, extra=""):
        file = directory / "SKILL.md"
        atomic_write_text(file, f"---\nname: {name}\ndescription: {description}\n{extra}---\n# Procedure\nPrivate body {name}\n")
        return file

    def refresh(self, **kwargs):
        self.catalog = refresh_skill_catalog(self.state, self.project, inventory_skills(self.state, **self.options))
        return prepare(self.state, self.project, self.sid, self.catalog, **kwargs)

    def read(self, file, start=1, end=None, **changes):
        lines = file.read_text(encoding="utf-8-sig").splitlines()
        payload = {"session_id": self.sid, "hook_event_name": "PostToolUse", "tool_name": "Read",
                   "tool_input": {"file_path": str(file)}, "tool_response": {"type": "text", "file": {
                       "content": "\n".join(lines[start-1:end]), "startLine": start,
                       "numLines": len(lines[start-1:end]), "totalLines": len(lines)}}}
        payload.update(changes)
        observe(self.state, self.project, payload)
        return payload

    def read_index(self):
        self.read(Path(self.catalog["path"]))

    def execution(self, tool="Bash", **tool_input):
        return preflight(self.state, self.project, {"session_id": self.sid, "tool_name": tool,
                        "tool_input": tool_input or {"command": "python custom_reader.py"}})

    def test_advice_tracks_index_then_actual_skill_read_without_permission_decision(self):
        result = self.execution()["hookSpecificOutput"]
        self.assertIn("스킬 목록", result["additionalContext"])
        self.assertNotIn('permissionDecision', result)
        self.read(self.reader)  # Skill first is not proof of catalogue comparison
        self.assertTrue(self.execution())
        self.read_index()
        # The earlier, complete body read is retained; don't read it twice.
        self.assertEqual({}, self.execution())
        self.assertEqual({}, self.execution("Write", file_path=str(self.project / "out.md")))

    def test_paged_reads_must_cover_every_line(self):
        file = Path(self.catalog["path"])
        self.read(file, end=5)
        self.assertFalse(load_session(self.sid, self.state)["skillWorkflow"]["indexRead"])
        self.read(file, start=7)
        self.assertFalse(load_session(self.sid, self.state)["skillWorkflow"]["indexRead"])
        self.read(file, start=6, end=6)
        self.assertTrue(load_session(self.sid, self.state)["skillWorkflow"]["indexRead"])
        self.read(self.reader, end=2)
        self.assertTrue(self.execution())
        self.read(self.reader, start=3)
        self.assertEqual({}, self.execution())

    def test_real_preflight_reminds_once_without_red_denial_or_auto_allow(self):
        from company_agent.skill_workflow import preflight as real_preflight
        payload = {'session_id':self.sid, 'tool_name':'Bash', 'tool_input':{'command':'pwd && ls -la'}}
        self.assertEqual({}, real_preflight(self.state, self.project, payload))
        payload['tool_input']['command'] = 'python custom.py'
        first = real_preflight(self.state, self.project, payload)
        self.assertIn('additionalContext', first['hookSpecificOutput'])
        self.assertNotIn('permissionDecision', first['hookSpecificOutput'])
        self.assertNotIn('systemMessage', first)
        for command in ('pwd && ls -la', 'python custom.py', 'powershell.exe -File missing.ps1 --help'):
            payload['tool_input']['command'] = command
            self.assertEqual({}, real_preflight(self.state, self.project, payload))
        self.turn = begin_turn(self.sid, 'MEDIUM', False, [], self.state)['turnId']
        self.refresh()
        self.assertTrue(real_preflight(self.state, self.project, payload))

    def test_optional_route_is_not_requested_by_advice(self):
        self.read_index()
        text = self.execution()['hookSpecificOutput']['additionalContext']
        self.assertIn('필수가 아닙니다', text)
        self.assertNotIn('skill route --session', text)

    def test_failed_or_wrong_content_does_not_create_read_receipt(self):
        file = Path(self.catalog["path"])
        self.read(file, hook_event_name="PostToolUseFailure")
        self.read(file, tool_response={"file": {"content": "made up", "startLine": 1}})
        self.assertFalse(load_session(self.sid, self.state)["skillWorkflow"]["indexRead"])
        self.read_index()
        self.read(self.reader, error="permission denied")
        self.assertTrue(self.execution())

    def test_new_turn_reuses_index_but_requires_new_choice(self):
        self.read_index()
        self.read(self.reader)
        self.turn = begin_turn(self.sid, "MEDIUM", False, [], self.state)["turnId"]
        context = self.refresh(prompt="Now create a presentation")
        self.assertTrue(context["indexRead"])
        self.assertIsNone(context["selected"])
        self.assertTrue(self.execution())
        with self.assertRaises(ValueError):
            select(self.state, self.project, self.sid, self.turn, name="presentation")
        self.read(self.deck)
        self.assertEqual({}, self.execution())
        self.turn = begin_turn(self.sid, "MEDIUM", False, [], self.state)["turnId"]
        self.refresh()
        select(self.state, self.project, self.sid, self.turn, name="fixture-reader")
        self.assertEqual({}, self.execution())

    def test_compaction_and_revision_reset_read_receipts(self):
        self.read_index()
        self.read(self.reader)
        self.assertFalse(self.refresh(compact=True)["indexRead"])
        self.read_index()
        self.read(self.reader)
        self.skill(self.claude / "skills/notes", "notes", "Take notes")
        self.assertFalse(self.refresh()["indexRead"])
        self.assertTrue(self.execution())

    def test_changed_or_deleted_selected_body_is_rejected_without_rescan(self):
        self.read_index()
        self.read(self.reader)
        atomic_write_text(self.reader, self.reader.read_text(encoding="utf-8") + "Changed\n")
        self.assertTrue(self.execution())
        self.reader.unlink()
        self.assertTrue(self.execution())

    def test_incomplete_scan_cannot_reuse_old_selection(self):
        self.read_index()
        self.read(self.reader)
        prepare(self.state, self.project, self.sid, {"status": "incomplete"})
        self.assertTrue(self.execution())
        # The priority manager itself must remain accessible for repair;
        # native permissions, not this preparation gate, govern its changes.
        prefix = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}"'
        self.assertEqual({}, self.execution(command=f"{prefix} skill reset --name fixture-reader"))

    def test_failed_prompt_preparation_does_not_leave_previous_turn_unlocked(self):
        self.read_index()
        self.read(self.reader)
        begin_turn(self.sid, "MEDIUM", False, [], self.state)
        self.assertTrue(self.execution())

    def test_old_turn_route_and_compound_command_do_not_bypass_preparation(self):
        prefix = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}"'
        command = f"{prefix} skill route --session {self.sid} --turn old --fallback no-relevant-skill"
        self.assertTrue(self.execution(command=command))
        self.assertTrue(self.execution(command=f"{prefix} skill list; python unsafe.py"))

    def test_project_preference_prevents_other_candidate_selection(self):
        personal = self.skill(self.project / ".claude/skills/fixture-reader", "fixture-reader", "Preferred custom reader")
        inventory = inventory_skills(self.state, **self.options)
        candidate = next(x for x in inventory["skills"] if x["source"] == "project")
        set_skill_preference(self.state, "fixture-reader", candidate["id"], **self.options)
        self.refresh()
        self.read_index()
        self.read(self.reader)
        self.assertTrue(self.execution())
        self.read(personal)
        self.assertEqual({}, self.execution())

    def test_ambiguous_candidates_cannot_satisfy_gate(self):
        self.skill(self.project / ".claude/skills/fixture-reader", "fixture-reader", "Another reader")
        self.refresh()
        self.read_index()
        self.read(self.reader)
        self.assertTrue(self.execution())

    def test_explicit_qualified_invocation_preserved(self):
        self.skill(self.project / ".claude/skills/fixture-reader", "fixture-reader", "Another reader")
        self.refresh(prompt="/company-agent:fixture-reader")
        self.read_index()
        self.read(self.reader)
        self.assertEqual({}, self.execution())

    def test_manual_only_skill_needs_explicit_invocation(self):
        self.skill(self.plugin / "skills/manual", "manual", "Explicit only", "disable-model-invocation: true\n")
        self.refresh()
        self.read_index()
        with self.assertRaises(ValueError):
            self.read(self.plugin / "skills/manual/SKILL.md")
        self.refresh(prompt="/company-agent:manual")
        self.read(self.plugin / "skills/manual/SKILL.md")
        self.assertIsNone(load_session(self.sid, self.state)['skillWorkflow']['selected'])
        observe(self.state, self.project, {'session_id': self.sid, 'hook_event_name': 'PostToolUse',
                'tool_name': 'Skill', 'tool_input': {'skill': 'company-agent:manual'}, 'tool_response': {'success': True}})
        self.assertEqual({}, self.execution())

    def test_support_read_neither_unlocks_nor_replaces_workflow(self):
        support = self.skill(self.plugin / "skills/helper", "helper", "General guidance", "company-agent-role: support\n")
        self.refresh()
        self.read_index()
        self.read(support)
        self.assertTrue(self.execution())
        self.read(self.reader)
        self.read(support)
        self.assertEqual("fixture-reader", load_session(self.sid, self.state)["skillWorkflow"]["selected"]["name"])

    def test_fallback_requires_index_and_current_turn(self):
        with self.assertRaises(ValueError):
            select(self.state, self.project, self.sid, self.turn, fallback="no-relevant-skill")
        self.read_index()
        with self.assertRaises(ValueError):
            select(self.state, self.project, self.sid, "old", fallback="no-relevant-skill")
        select(self.state, self.project, self.sid, self.turn, fallback="no-relevant-skill")
        self.assertEqual({}, self.execution())

    def test_read_lookup_and_choices_are_not_execution_gated(self):
        for tool in ("Read", "Glob", "Grep", "AskUserQuestion", "Skill"):
            self.assertEqual({}, self.execution(tool))
        prefix = f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}"'
        for tail in ("skill list", "skill resolve fixture-reader", "business doctor"):
            self.assertEqual({}, self.execution(command=f"{prefix} {tail}"))
        self.assertTrue(self.execution(command=f'{prefix} business eml-read --file "{self.project / "in.eml"}"'))

    def test_no_prompt_or_bodies_in_metadata(self):
        self.refresh(prompt="PRIVATE REQUEST CONTENT")
        self.read_index()
        self.read(self.reader)
        files = list((self.state / "sessions").glob("*.json")) + [Path(self.catalog["path"]).with_suffix(".json")]
        for file in files:
            text = file.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE REQUEST", text)
            self.assertNotIn("Private body", text)

    def test_other_project_and_tampered_index_rejected(self):
        self.read_index()
        self.read(self.reader)
        other = self.root / "other"
        other.mkdir()
        self.assertTrue(preflight(self.state, other, {"session_id": self.sid, "tool_name": "Write"}))
        atomic_write_text(Path(self.catalog["path"]), "Forged")
        self.assertTrue(self.execution())

    def test_skill_tool_success_matches_exact_invocation(self):
        self.read_index()
        payload = {"session_id": self.sid, "hook_event_name": "PostToolUse", "tool_name": "Skill",
                   "tool_input": {"skill": "company-agent:fixture-reader"}, "tool_response": {"success": True}}
        observe(self.state, self.project, payload)
        self.assertEqual({}, self.execution())

    def test_native_skill_before_index_keeps_receipt_without_fabricating_index_read(self):
        payload = {"session_id": self.sid, "hook_event_name": "PostToolUse", "tool_name": "Skill",
                   "tool_input": {"skill": "company-agent:fixture-reader"}, "tool_response": {"success": True}}
        observe(self.state, self.project, payload)
        route = load_session(self.sid, self.state)["skillWorkflow"]
        self.assertFalse(route["indexRead"])
        self.assertEqual("fixture-reader", route["selected"]["name"])
        self.read_index()
        self.assertEqual({}, self.execution())

    def test_short_powershell_route_bookkeeping_stays_out_of_mutations(self):
        from company_agent.skill_workflow import internal_command
        shell = self.root / "WindowsPowerShell" / "powershell.exe"
        command = (f'powershell.exe -NoLogo -NoProfile -File "{SCRIPTS / "Invoke-CompanyAgent.ps1"}"'
                   f' -Mode Cli skill route --session {self.sid} --turn {self.turn} --name fixture-reader')
        with patch("company_agent.execution_contract._powershell", return_value=shell), patch("shutil.which", return_value=str(shell)):
            self.assertTrue(internal_command(command, self.sid, load_session(self.sid, self.state), self.state))
            record_activity({"session_id": self.sid, "tool_name": "Bash", "tool_input": {"command": command}}, self.state)
        self.assertEqual(0, load_session(self.sid, self.state)["mutationCount"])

    def test_worker_receives_selected_path_not_all_skill_bodies(self):
        from company_agent.native_runtime import worker_runtime_input
        self.read_index()
        self.read(self.reader)
        with patch("company_agent.native_runtime._skill_routing", return_value=([], {"status": "ready", "catalog": self.catalog})):
            result = worker_runtime_input(self.plugin, self.project, {"session_id": self.sid, "tool_input": {
                "subagent_type": "company-agent:medium-worker", "prompt": "Analyze only the supplied source", "model": "sonnet"}})
        text = result["hookSpecificOutput"]["updatedInput"]["prompt"]
        self.assertIn('"selectedSkill":{"name":"fixture-reader"', text)
        self.assertIn(str(self.reader).replace("\\", "\\\\"), text)
        self.assertNotIn("Private body", text)
        self.assertNotIn("permissionDecision", result["hookSpecificOutput"])

    def test_route_cli_is_internal_not_a_business_mutation(self):
        self.read_index()
        command = (f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}" skill route --session {self.sid}'
                   f' --turn {self.turn} --fallback no-relevant-skill --state-root "{self.state}"')
        self.assertEqual({}, self.execution(command=command))
        old = Path.cwd()
        try:
            os.chdir(self.project)
            with contextlib.redirect_stdout(io.StringIO()):
                result = cli_main(["skill", "route", "--session", self.sid, "--turn", self.turn,
                                   "--fallback", "no-relevant-skill", "--state-root", str(self.state)])
            self.assertEqual(0, result)
        finally:
            os.chdir(old)
        record_activity({"session_id": self.sid, "tool_name": "Bash", "hook_event_name": "PostToolUse",
                         "tool_input": {"command": command}, "tool_response": {"stdout": "{}"}}, self.state)
        state = load_session(self.sid, self.state)
        self.assertEqual(0, state["mutationCount"])
        self.assertEqual(0, state.get("taskToolCount", 0))


if __name__ == "__main__":
    unittest.main()
