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
from company_agent.cli import main
from company_agent.frontmatter import dump_frontmatter
from company_agent.native_runtime import MAX_RUNTIME_CONTEXT_CHARS, runtime_context, session_start
from company_agent.paths import atomic_write_json, atomic_write_text


class SkillPreferenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.claude = self.root / "claude"
        self.project = self.root / "project  with spaces"
        self.other = self.root / "another-project"
        self.project.mkdir()
        self.other.mkdir()
        self.plugin = self.root / "plugin"
        atomic_write_json(self.plugin / ".claude-plugin" / "plugin.json", {"name": "company-agent", "version": "1.0.0"})
        self.user_skill = self.skill(self.claude / "skills" / "report", "report", "User report workflow")
        self.project_skill = self.skill(self.project / ".claude" / "skills" / "report", "report", "Project report workflow")
        self.company_skill = self.skill(self.plugin / "skills" / "report", "report", "Company report workflow")
        self.env = patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.claude), "COMPANY_AGENT_USER_STATE": str(self.state),
            "COMPANY_AGENT_PLUGIN_ROOT": str(self.plugin), "COMPANY_AGENT_KNOWLEDGE_BASE": "",
            "COMPANY_AGENT_SCOPE": "User", "CLAUDE_ENV_FILE": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)

    def skill(self, directory, name, description):
        path = directory / "SKILL.md"
        atomic_write_text(path, dump_frontmatter({"name": name, "description": description}, "BODY-MUST-STAY-OUT-OF-CONTEXT"))
        return path

    def cli(self, operation, *args, expected=0, project=None):
        output, errors = io.StringIO(), io.StringIO()
        arguments = ["skill", operation, "--state-root", str(self.state), "--claude-root", str(self.claude),
                     "--plugin-root", str(self.plugin), "--project-root", str(project or self.project), *args]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = main(arguments)
        self.assertEqual(expected, result, errors.getvalue() + output.getvalue())
        return json.loads(output.getvalue() if result == 0 else errors.getvalue())

    def candidates(self):
        report = self.cli("inventory")
        return {item["source"]: item for item in report["skills"] if item["name"] == "report"}

    def startup(self, project=None):
        result = session_start(self.plugin, project or self.project)
        context = json.loads(result["hookSpecificOutput"]["additionalContext"])["company_agent_runtime"]
        return context["skillSelection"], result.get("systemMessage", "")

    def test_inventory_is_read_only_and_project_preference_drives_search_and_hook(self):
        before = {file: file.read_bytes() for file in (self.user_skill, self.project_skill, self.company_skill)}
        candidates = self.candidates()
        self.assertEqual({"user", "project", "company"}, set(candidates))
        self.assertFalse(self.state.exists())
        self.cli("prefer", "--name", "report", "--candidate", candidates["project"]["id"], "--scope", "project")
        found = self.cli("search", "report")
        self.assertEqual([candidates["project"]["id"]], [item["id"] for item in found["skills"]])
        context = json.loads(runtime_context(self.plugin, self.project, "report"))["company_agent_runtime"]
        self.assertEqual([], context["preferredSkills"])
        catalog=Path(context['skillSelection']['catalog']['path']).read_text(encoding='utf-8')
        project_section=catalog.split('## 프로젝트 스킬')[1].split('## ')[0]
        self.assertIn('우선 선택됨',project_section)
        self.assertEqual(candidates['project']['id'],self.cli('resolve','report')['resolution']['selectedId'])
        self.assertFalse(context["skillSelection"]["nativePrecedenceChanged"])
        self.assertNotIn("BODY-MUST-STAY", json.dumps(context))
        self.assertEqual(before, {file: file.read_bytes() for file in before})

    def test_default_then_project_override_and_reset_are_isolated(self):
        candidates = self.candidates()
        self.cli("prefer", "--name", "report", "--candidate", candidates["user"]["id"], "--scope", "default")
        self.cli("prefer", "--name", "report", "--candidate", candidates["project"]["id"], "--scope", "project")
        selected = self.cli("resolve", "report")
        self.assertEqual(candidates["project"]["id"], selected["resolution"]["selectedId"])
        elsewhere = self.cli("resolve", "report", project=self.other)
        self.assertEqual(candidates["user"]["id"], elsewhere["resolution"]["selectedId"])
        self.cli("reset", "--name", "report", "--scope", "project")
        self.assertEqual(candidates["user"]["id"], self.cli("resolve", "report")["resolution"]["selectedId"])

    def test_selected_overlap_keeps_inventory_but_has_no_repeated_startup_warning(self):
        candidate = self.candidates()["project"]
        self.cli("prefer", "--name", "report", "--candidate", candidate["id"], "--scope", "project")
        before = {path: path.read_bytes() for path in (self.user_skill, self.project_skill, self.company_skill)}
        for _ in range(2):
            selection, message = self.startup()
            self.assertEqual(1, selection["conflictCount"])
            self.assertEqual(1, selection["resolvedOverlapCount"])
            self.assertEqual(0, selection["unresolvedCount"])
            self.assertEqual("selected", selection["conflicts"][0]["status"])
            self.assertNotIn("/company-agent:skills", message)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_source_order_resolved_overlap_has_no_startup_warning(self):
        self.cli("order", "--sources", "project", "user", "company", "--scope", "project")
        selection, message = self.startup()
        self.assertEqual(1, selection["resolvedOverlapCount"])
        self.assertEqual(0, selection["unresolvedCount"])
        self.assertNotIn("/company-agent:skills", message)

    def test_distinct_namespaced_overlap_is_quiet_but_still_requires_workflow_choice(self):
        selection, message = self.startup(self.other)
        self.assertEqual(1, selection["conflictCount"])
        self.assertEqual(1, selection["namespacedOverlapCount"])
        self.assertEqual("unresolved", selection["conflicts"][0]["status"])
        self.assertEqual(0, selection["unresolvedCount"])
        self.assertNotIn("/company-agent:skills", message)
        self.assertEqual([], self.cli("search", "report", project=self.other)["skills"])

    def test_same_namespaced_invocation_from_two_plugins_still_warns(self):
        plugins = {}
        for number in (1, 2):
            root = self.root / f"vendor-{number}"
            atomic_write_json(root / ".claude-plugin" / "plugin.json", {"name": "vendor", "version": "1.0.0"})
            self.skill(root / "skills" / "report", "report", "Vendor report workflow")
            plugins[f"vendor@market-{number}"] = [{"scope": "user", "installPath": str(root)}]
        atomic_write_json(self.claude / "plugins" / "installed_plugins.json", {"plugins": plugins})
        atomic_write_json(self.claude / "settings.json", {"enabledPlugins": {name: True for name in plugins}})
        selection, message = self.startup(self.other)
        self.assertEqual("namespaced-overlap", selection["conflicts"][0]["kind"])
        self.assertEqual(1, selection["unresolvedCount"])
        self.assertIn("같은 이름으로 사용할 수 있는 Skill", message)

    def test_unresolved_native_collision_has_specific_startup_warning(self):
        selection, message = self.startup()
        self.assertEqual(1, selection["unresolvedCount"])
        self.assertEqual(0, selection["scanWarningCount"])
        self.assertIn("우선 Skill을 선택", message)
        self.assertNotIn("일부 Skill 정보를 확인하지 못했습니다", message)
        self.assertIn("/company-agent:skills", message)

    def test_stale_preference_warns_even_when_only_one_candidate_remains(self):
        candidate = self.candidates()["company"]
        self.cli("prefer", "--name", "report", "--candidate", candidate["id"], "--scope", "default")
        self.company_skill.unlink()
        selection, message = self.startup(self.other)
        self.assertEqual(0, selection["conflictCount"])
        self.assertEqual(1, selection["stalePreferenceCount"])
        self.assertEqual(0, selection["scanWarningCount"])
        self.assertEqual(1, selection["warningCount"])
        self.assertIn("이전에 선택한 Skill을 찾지 못했습니다", message)
        self.assertNotIn("일부 Skill 정보를 확인하지 못했습니다", message)

    def test_scan_failure_remains_visible_after_overlap_is_resolved(self):
        candidate = self.candidates()["project"]
        self.cli("prefer", "--name", "report", "--candidate", candidate["id"], "--scope", "project")
        atomic_write_text(self.claude / "settings.json", "{INVALID-PRIVATE-SETTINGS")
        selection, message = self.startup()
        self.assertEqual("incomplete", selection["status"])
        self.assertEqual(1, selection["resolvedOverlapCount"])
        self.assertEqual(0, selection["unresolvedCount"])
        self.assertGreater(selection["scanWarningCount"], 0)
        self.assertIn("일부 Skill 정보를 확인하지 못했습니다", message)
        self.assertNotIn("INVALID-PRIVATE-SETTINGS", message)
        self.assertNotIn("우선 Skill을 선택", message)

    def test_unavailable_preferences_have_specific_non_destructive_warning(self):
        path = self.state / "config" / "skill-preferences.json"
        atomic_write_json(path, {"schemaVersion": 999, "private": "DO-NOT-LEAK"})
        before = path.read_bytes()
        selection, message = self.startup()
        self.assertEqual("unavailable", selection["status"])
        self.assertIn("Skill 우선 설정을 읽지 못했습니다", message)
        self.assertIn("기존 설정은 보존했습니다", message)
        self.assertNotIn("DO-NOT-LEAK", message)
        self.assertEqual(before, path.read_bytes())

    def test_unclassified_warning_is_not_silenced_by_ready_status(self):
        found = {"skills": [], "conflicts": [], "complete": True, "warnings": ["A new inventory warning type."]}
        with patch("company_agent.skill_registry.search_skills", return_value=found):
            selection, message = self.startup()
        self.assertEqual("ready", selection["status"])
        self.assertEqual(1, selection["warningCount"])
        self.assertEqual(1, selection["scanWarningCount"])
        self.assertIn("일부 Skill 정보를 확인하지 못했습니다", message)

    def test_stale_choice_and_incomplete_scan_both_remain_visible(self):
        candidate = self.candidates()["company"]
        self.cli("prefer", "--name", "report", "--candidate", candidate["id"], "--scope", "default")
        self.company_skill.unlink()
        atomic_write_text(self.claude / "settings.json", "{INVALID-PRIVATE-SETTINGS")
        selection, message = self.startup(self.other)
        self.assertEqual(1, selection["stalePreferenceCount"])
        self.assertGreater(selection["scanWarningCount"], 0)
        self.assertIn("일부 Skill 정보를 확인하지 못했습니다", message)
        self.assertIn("이전에 선택한 Skill을 찾지 못했습니다", message)

    def test_unresolved_and_stale_choices_do_not_inject_arbitrary_workflows(self):
        self.assertEqual([], self.cli("search", "report")["skills"])
        chosen = self.candidates()["project"]
        self.cli("prefer", "--name", "report", "--candidate", chosen["id"], "--scope", "project")
        self.project_skill.unlink()
        resolution = self.cli("resolve", "report")["resolution"]
        self.assertEqual("stale-choice", resolution["status"])
        context = json.loads(runtime_context(self.plugin, self.project, "report"))["company_agent_runtime"]
        self.assertEqual([], context["preferredSkills"])
        self.assertEqual([], context["personalSkills"])
        self.assertIn("/company-agent:skills", session_start(self.plugin, self.project).get("systemMessage", ""))

    def test_incoming_preference_persists_without_modifying_skills(self):
        original = self.user_skill.read_bytes()
        result = self.cli("prefer-incoming", "--incoming-plugin", str(self.plugin), "--scope", "project")
        self.assertEqual(1, len(result["changes"]))
        picked = self.cli("search", "report")["skills"]
        self.assertEqual("company", picked[0]["source"])
        self.assertEqual("company-agent:report", picked[0]["invocation"])
        self.assertEqual(original, self.user_skill.read_bytes())

    def test_invalid_selection_and_future_preferences_are_not_overwritten(self):
        selected = self.candidates()["user"]
        self.cli("prefer", "--name", "report", "--candidate", selected["id"], "--scope", "default")
        path = self.state / "config" / "skill-preferences.json"
        before = path.read_bytes()
        self.cli("prefer", "--name", "report", "--candidate", "unknown-candidate", "--scope", "project", expected=1)
        self.assertEqual(before, path.read_bytes())
        atomic_write_json(path, {"schemaVersion": 999, "private": "DO-NOT-LEAK"})
        future = path.read_bytes()
        context_text = runtime_context(self.plugin, self.project, "report")
        context = json.loads(context_text)["company_agent_runtime"]
        self.assertEqual("unavailable", context["skillSelection"]["status"])
        self.assertEqual([], context["preferredSkills"])
        self.assertNotIn("DO-NOT-LEAK", context_text)
        self.assertEqual(future, path.read_bytes())

    def test_many_conflicts_remain_bounded_and_bodies_are_never_injected(self):
        for number in range(20):
            name = f"report-{number:02}"
            for parent in (self.claude / "skills", self.project / ".claude" / "skills"):
                self.skill(parent / name, name, "report " + "long-description " * 100)
        context = runtime_context(self.plugin, self.project, "report")
        self.assertLessEqual(len(context), MAX_RUNTIME_CONTEXT_CHARS)
        self.assertNotIn("BODY-MUST-STAY", context)
        data = json.loads(context)["company_agent_runtime"]
        self.assertLessEqual(len(data["skillSelection"]["conflicts"]), 4)

    def test_long_natural_request_keeps_preferences_and_bounded_context(self):
        candidate = self.candidates()["project"]
        self.cli("prefer", "--name", "report", "--candidate", candidate["id"], "--scope", "project")
        text = runtime_context(self.plugin, self.project, "report please follow this workflow " + "long-task-input " * 1000)
        data = json.loads(text)["company_agent_runtime"]
        self.assertEqual("ready", data["skillSelection"]["status"])
        self.assertEqual([], data["preferredSkills"])
        catalog=Path(data['skillSelection']['catalog']['path']).read_text(encoding='utf-8')
        self.assertIn('우선 선택됨',catalog.split('## 프로젝트 스킬')[1].split('## ')[0])
        self.assertEqual(candidate['id'],self.cli('resolve','report')['resolution']['selectedId'])
        self.assertLessEqual(len(text), MAX_RUNTIME_CONTEXT_CHARS)

    def test_project_only_candidate_cannot_be_mistaken_for_global_default(self):
        candidate = self.candidates()["project"]
        self.cli("prefer", "--name", "report", "--candidate", candidate["id"], "--scope", "default", expected=1)
        self.assertFalse((self.state / "config" / "skill-preferences.json").exists())


if __name__ == "__main__":
    unittest.main()
