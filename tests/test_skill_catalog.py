from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.skill_catalog import refresh_skill_catalog
from company_agent.skill_registry import inventory_skills, set_skill_preference
from company_agent.native_runtime import MAX_RUNTIME_CONTEXT_CHARS, runtime_context


class SkillCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.claude = self.root / "claude"
        self.project = self.root / "한글 project"
        self.project.mkdir()
        self.plugin = self.root / "plugin"
        atomic_write_json(self.plugin / ".claude-plugin" / "plugin.json", {"name": "company-agent", "version": "1.3.2"})
        self.skill(self.plugin / "skills" / "mail", "mail", "Search and summarize Outlook email")
        self.options = {"project_root": self.project, "claude_root": self.claude, "plugin_root": self.plugin}
        self.env = patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude),
                              "COMPANY_AGENT_USER_STATE": str(self.state),
                              "COMPANY_AGENT_KNOWLEDGE_BASE": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def skill(self, directory, name, description):
        atomic_write_text(directory / "SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\nBODY-PRIVATE-NOT-IN-CATALOG\n")

    def refresh(self, **overrides):
        options = {**self.options, **overrides}
        snapshot = inventory_skills(self.state, **options)
        return refresh_skill_catalog(self.state, options["project_root"], snapshot)

    def test_first_use_lists_all_sources_not_only_keyword_matches(self):
        self.skill(self.claude / "skills" / "diagram", "diagram", "Draw architecture diagrams")
        personal = self.state / "personal-root" / ".claude" / "skills" / "notes"
        self.skill(personal, "notes", "Record meeting notes")
        self.skill(self.project / ".claude" / "skills" / "report", "report", "Local reports")
        result = self.refresh()
        self.assertEqual(4, result["count"])
        catalog = Path(result["path"])
        self.assertTrue(catalog.is_relative_to(self.state / "skill-catalogs"))
        text = catalog.read_text(encoding="utf-8")
        for name in ("mail", "diagram", "notes", "report"):
            self.assertIn(name, text)
        self.assertNotIn("BODY-PRIVATE", text)
        self.assertFalse((self.project / "SKILL_CATALOG.md").exists())

    def test_unchanged_does_not_rewrite_and_edits_install_delete_refresh(self):
        first = self.refresh()
        file = Path(first["path"])
        before_time = file.stat().st_mtime_ns
        with patch("company_agent.skill_catalog.os.replace", side_effect=AssertionError("unchanged catalogue was written")):
            self.assertEqual(first, self.refresh())
        self.assertEqual(before_time, file.stat().st_mtime_ns)
        added = self.claude / "skills" / "ppt"
        self.skill(added, "ppt", "Editable slide decks")
        installed = self.refresh()
        self.assertNotEqual(first["revision"], installed["revision"])
        self.assertIn("Editable slide decks", file.read_text(encoding="utf-8"))
        self.skill(added, "ppt", "Presentation using corporate template")
        edited = self.refresh()
        self.assertNotEqual(installed["revision"], edited["revision"])
        with (added / "SKILL.md").open("a", encoding="utf-8") as stream:
            stream.write("Body-only edit")
        body_edited = self.refresh()
        self.assertNotEqual(edited["revision"], body_edited["revision"])
        self.assertNotIn("Body-only edit", file.read_text(encoding="utf-8"))
        (added / "SKILL.md").unlink()
        deleted = self.refresh()
        self.assertEqual(first["revision"], deleted["revision"])
        self.assertNotIn("| ppt |", file.read_text(encoding="utf-8"))

    def test_plugin_enable_disable_and_removal_refresh(self):
        external = self.claude / "plugins" / "cache" / "vendor" / "extras" / "1"
        atomic_write_json(external / ".claude-plugin" / "plugin.json", {"name": "extras"})
        self.skill(external / "skills" / "charts", "charts", "Make charts")
        registration = {"plugins": {"extras@vendor": [{"scope": "user", "installPath": str(external)}]}}
        atomic_write_json(self.claude / "plugins" / "installed_plugins.json", registration)
        atomic_write_json(self.claude / "settings.json", {"enabledPlugins": {"extras@vendor": True}})
        enabled = self.refresh()
        self.assertEqual(2, enabled["count"])
        atomic_write_json(self.claude / "settings.json", {"enabledPlugins": {"extras@vendor": False}})
        disabled = self.refresh()
        self.assertEqual(1, disabled["count"])
        self.assertNotEqual(enabled["revision"], disabled["revision"])
        atomic_write_json(self.claude / "settings.json", {"enabledPlugins": {"extras@vendor": True}})
        self.assertEqual(enabled["revision"], self.refresh()["revision"])
        atomic_write_json(self.claude / "plugins" / "installed_plugins.json", {"plugins": {}})
        self.assertEqual(1, self.refresh()["count"])

    def test_folders_and_preferences_are_isolated_and_explicit(self):
        second = self.root / "other project"
        second.mkdir()
        self.skill(self.project / ".claude" / "skills" / "mail", "mail", "Project mailbox workflow")
        first = self.refresh()
        other = self.refresh(project_root=second)
        self.assertNotEqual(first["path"], other["path"])
        self.assertEqual(2, first["count"])
        self.assertEqual(1, other["count"])
        self.assertIn("같은 이름·선택 필요", Path(first["path"]).read_text(encoding="utf-8"))
        candidate = next(item for item in inventory_skills(self.state, **self.options)["skills"] if item["source"] == "project")
        set_skill_preference(self.state, "mail", candidate["id"], **self.options)
        selected = self.refresh()
        self.assertNotEqual(first["revision"], selected["revision"])
        self.assertIn("우선 선택됨", Path(first["path"]).read_text(encoding="utf-8"))
        self.assertEqual(other, self.refresh(project_root=second))
        Path(candidate["path"]).unlink()
        missing = self.refresh()
        self.assertIn("이전 선택 없음·재확인 필요", Path(missing["path"]).read_text(encoding="utf-8"))

    def test_incomplete_scan_preserves_last_good_file_without_offering_stale_pointer(self):
        before = self.refresh()
        file = Path(before["path"])
        original = file.read_bytes()
        incomplete = inventory_skills(self.state, **self.options)
        incomplete.update(complete=False, skills=[])
        result = refresh_skill_catalog(self.state, self.project, incomplete)
        self.assertEqual({"status": "incomplete"}, result)
        self.assertEqual(original, file.read_bytes())

    def test_metadata_is_inert_and_tampered_generated_file_is_rebuilt(self):
        self.skill(self.claude / "skills" / "bad", "bad", '<script>alert(1)</script> | `evil` [go](https://example.com)')
        result = self.refresh()
        file = Path(result["path"])
        text = file.read_text(encoding="utf-8")
        self.assertNotIn("<script>", text)
        self.assertIn("&#124;", text)
        self.assertNotIn("`evil`", text)
        self.assertNotIn("[go](", text)
        file.write_text("Forged catalogue", encoding="utf-8")
        self.assertEqual(result, self.refresh())
        self.assertEqual(text, file.read_text(encoding="utf-8"))

    def test_runtime_exposes_full_catalogue_even_for_korean_request_with_no_word_match(self):
        self.skill(self.claude / "skills" / "deck", "deck", "Create editable PowerPoint presentations")
        context = runtime_context(self.plugin, self.project, "발표자료 만들어줘 PRIVATE-PROMPT")
        data = json.loads(context)["company_agent_runtime"]
        catalog = data["skillSelection"]["catalog"]
        self.assertEqual("ready", catalog["status"])
        self.assertEqual([], data["preferredSkills"])
        self.assertIn("PowerPoint", Path(catalog["path"]).read_text(encoding="utf-8"))
        self.assertNotIn("PRIVATE-PROMPT", Path(catalog["path"]).read_text(encoding="utf-8"))
        self.assertLessEqual(len(context), MAX_RUNTIME_CONTEXT_CHARS)
        self.assertEqual('inline', data['skillIndex']['mode'])
        self.assertIn("Create editable PowerPoint presentations", context)
        self.assertNotIn('PRIVATE BODY', context)

    def test_runtime_catalog_failure_does_not_break_existing_routing(self):
        with patch("company_agent.skill_catalog.refresh_skill_catalog", side_effect=PermissionError("denied")):
            context = json.loads(runtime_context(self.plugin, self.project, "mail"))["company_agent_runtime"]
        self.assertEqual("unavailable", context["skillSelection"]["catalog"]["status"])
        self.assertEqual("mail", context["preferredSkills"][0]["name"])

    def test_ready_catalog_omits_even_keyword_matched_cards(self):
        context=json.loads(runtime_context(self.plugin,self.project,'mail'))['company_agent_runtime']
        self.assertEqual('ready',context['skillSelection']['catalog']['status'])
        self.assertEqual([],context['preferredSkills'])
        self.assertIn('Search and summarize Outlook email',json.dumps(context))
        self.assertEqual('inline',context['skillIndex']['mode'])
        self.assertNotIn('후보 식별값',Path(context['skillSelection']['catalog']['path']).read_text(encoding='utf-8'))

    def test_future_state_is_not_written(self):
        first = self.refresh()
        original = Path(first["path"]).read_bytes()
        atomic_write_json(self.state / "state-format.json", {"schemaVersion": 999})
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(original, Path(first["path"]).read_bytes())

    def test_redirected_catalog_directory_is_rejected(self):
        self.state.mkdir()
        external = self.root / "external"
        external.mkdir()
        marker = external / "preserve.txt"
        marker.write_text("preserve", encoding="utf-8")
        link = self.state / "skill-catalogs"
        if os.name == "nt":
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(external)],
                                    capture_output=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
        else:
            link.symlink_to(external, target_is_directory=True)
        try:
            with self.assertRaises(ValueError):
                self.refresh()
            self.assertEqual([marker], list(external.iterdir()))
        finally:
            if os.name == "nt":
                # Remove exactly the fixture junction itself, never its target.
                self.assertTrue(link.is_junction())
                os.rmdir(link)
            else:
                link.unlink()

    def test_empty_complete_inventory_clears_deleted_entries(self):
        first = self.refresh()
        (self.plugin / "skills" / "mail" / "SKILL.md").unlink()
        result = self.refresh()
        self.assertEqual(0, result["count"])
        self.assertNotEqual(first["revision"], result["revision"])
        self.assertNotIn("| mail |", Path(result["path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
