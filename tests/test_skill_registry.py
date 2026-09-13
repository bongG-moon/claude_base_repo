from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent.skill_registry import (
    inventory_skills, reset_skill_preferences, resolve_skill, search_skills,
    set_skill_preference, set_skill_source_order,
)


class SkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.claude = self.root / "claude"
        self.project = self.root / "project"
        self.project.mkdir()
        self.options = {"claude_root": self.claude}

    def test_inventory_summary_counts_exact_observed_candidates(self):
        self.skill(self.claude / "skills", "alpha")
        self.skill(self.claude / "skills", "beta")
        result = inventory_skills(self.state, **self.options)
        self.assertEqual(len(result["skills"]), result["summary"]["total"])
        self.assertEqual(2, result["summary"]["bySource"]["user"])
        self.assertEqual(result["summary"]["total"], sum(result["summary"]["bySource"].values()))
        self.assertFalse(self.state.exists())

    def json_file(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def skill(self, root: Path, folder: str, *, name: str | None = None, description: str = "Sample metadata", body: str = "INSTRUCTION BODY MUST NOT BE RETURNED") -> Path:
        file = root / folder / "SKILL.md"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"---\nname: {name or folder}\ndescription: {description}\n---\n{body}\n", encoding="utf-8")
        return file

    def plugin(self, root: Path, *, name: str = "company-agent", skills: tuple[str, ...] = ("review",)) -> Path:
        self.json_file(root / ".claude-plugin" / "plugin.json", {"name": name, "version": root.name})
        for skill in skills:
            self.skill(root / "skills", skill)
        return root

    def inventory(self, **options: object) -> dict:
        return inventory_skills(self.state, **{**self.options, **options})

    def choose(self, name: str, candidate: dict, **options: object) -> dict:
        return set_skill_preference(self.state, name, candidate["id"], **{**self.options, **options})

    def directory_link(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("Symbolic links are unavailable on this host.")
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            if result.returncode:
                self.skipTest("Symbolic links and junctions are unavailable on this host.")

    def overlaps(self) -> tuple[Path, dict, dict]:
        self.skill(self.claude / "skills", "review")
        plugin = self.plugin(self.root / "company" / "1.0")
        result = self.inventory(plugin_root=plugin)
        return plugin, next(item for item in result["skills"] if item["source"] == "user"), next(item for item in result["skills"] if item["source"] == "company")

    def test_inventory_is_read_only_and_exact_name_conflicts_do_not_claim_semantic_duplicates(self) -> None:
        self.skill(self.claude / "skills", "Review", name="Review")
        self.skill(self.state / "personal-root" / ".claude" / "skills", "review")
        self.skill(self.claude / "skills", "different-name", description="Sample metadata")
        result = self.inventory()
        self.assertFalse((self.state / "config").exists())
        self.assertEqual(len(result["conflicts"]), 1)
        conflict = result["conflicts"][0]
        self.assertEqual((conflict["name"], conflict["kind"], conflict["resolution"]["status"]), ("review", "workflow-name-overlap", "unresolved"))
        self.assertNotIn("INSTRUCTION BODY", str(result))
        self.assertEqual(len(result["skills"]), 3)

    def test_native_plain_collisions_and_workflow_only_overlaps_are_distinct(self) -> None:
        self.skill(self.claude / "skills", "review")
        self.skill(self.project / ".claude" / "skills", "review")
        native = self.inventory(project_root=self.project)
        self.assertEqual(native["conflicts"][0]["kind"], "native-name-collision")
        self.skill(self.state / "personal-root" / ".claude" / "skills", "helper")
        knowledge = self.root / "knowledge"
        self.skill(knowledge / ".claude" / "skills", "helper")
        workflows = self.inventory(knowledge_root=knowledge)
        conflict = next(item for item in workflows["conflicts"] if item["name"] == "helper")
        self.assertEqual(conflict["kind"], "workflow-name-overlap")
        self.assertTrue(all(item["invocation"] == "" for item in conflict["candidates"]))

    def test_incoming_company_replaces_old_version_and_id_survives_upgrade(self) -> None:
        self.skill(self.claude / "skills", "review")
        old = self.plugin(self.root / "company" / "0.9")
        new = self.plugin(self.root / "payload" / "1.0")
        old_company = next(item for item in self.inventory(plugin_root=old)["skills"] if item["source"] == "company")
        preview = self.inventory(plugin_root=old, incoming_plugin=new)
        self.assertEqual(len(preview["skills"]), 2)
        incoming = next(item for item in preview["skills"] if item["incoming"])
        self.assertEqual(incoming["id"], old_company["id"])
        self.choose("review", incoming, incoming_plugin=new)
        self.skill(new / "skills", "review", description="Updated metadata and implementation")
        updated = resolve_skill(self.state, "review", plugin_root=new, **self.options)
        self.assertEqual(updated["resolution"]["selectedId"], incoming["id"])
        self.assertEqual(updated["resolution"]["status"], "selected")
        self.assertEqual(preview["conflicts"][0]["kind"], "namespaced-overlap")

    def test_incoming_standalone_personal_skill_id_matches_final_destination(self) -> None:
        incoming_file = self.skill(self.root / "staging", "local-helper")
        candidate = self.inventory(incoming_skill=incoming_file)["skills"][0]
        self.choose("local-helper", candidate, incoming_skill=incoming_file)
        self.skill(self.state / "personal-root" / ".claude" / "skills", "local-helper")
        final = resolve_skill(self.state, "local-helper", **self.options)
        self.assertEqual(final["resolution"]["selectedId"], candidate["id"])
        self.assertEqual(final["resolution"]["status"], "selected")

    def test_installed_plugins_require_enabled_scope_and_relevant_project(self) -> None:
        active = self.plugin(self.root / "cache" / "active" / "1.0", name="active")
        disabled = self.plugin(self.root / "cache" / "disabled" / "1.0", name="disabled")
        unrelated = self.plugin(self.root / "cache" / "other" / "1.0", name="other")
        local = self.plugin(self.root / "cache" / "local" / "1.0", name="local")
        plugins = {
            "active@market": [{"scope": "user", "installPath": str(active)}],
            "disabled@market": [{"scope": "user", "installPath": str(disabled)}],
            "other@market": [{"scope": "project", "installPath": str(unrelated), "projectPath": str(self.root / "other-project")}],
            "local@market": [{"scope": "local", "installPath": str(local), "projectPath": str(self.project)}],
        }
        self.json_file(self.claude / "plugins" / "installed_plugins.json", {"version": 2, "plugins": plugins})
        self.json_file(self.claude / "settings.json", {"enabledPlugins": {"active@market": True, "disabled@market": False, "other@market": True, "local@market": True}})
        self.assertEqual({item["origin"] for item in self.inventory()["skills"]}, {"active@market"})
        scoped = self.inventory(project_root=self.project)
        self.assertEqual({item["origin"] for item in scoped["skills"]}, {"active@market", "local@market"})
        self.json_file(self.project / ".claude" / "settings.local.json", {"enabledPlugins": {"active@market": False, "disabled@market": True}})
        scoped = self.inventory(project_root=self.project)
        self.assertEqual({item["origin"] for item in scoped["skills"]}, {"disabled@market", "local@market"})

    def test_installed_company_and_incoming_company_are_one_logical_origin(self) -> None:
        old = self.plugin(self.root / "cache" / "0.9")
        new = self.plugin(self.root / "payload" / "1.0")
        self.json_file(self.claude / "plugins" / "installed_plugins.json", {"plugins": {"company-agent@local": [{"scope": "user", "installPath": str(old)}]}})
        self.json_file(self.claude / "settings.json", {"enabledPlugins": {"company-agent@local": True}})
        preview = self.inventory(incoming_plugin=new)
        self.assertEqual(len(preview["skills"]), 1)
        self.assertTrue(preview["skills"][0]["incoming"])
        self.assertEqual(preview["conflicts"], [])

    def test_malformed_plugin_records_warn_without_crashing_or_becoming_available(self) -> None:
        self.json_file(self.claude / "plugins" / "installed_plugins.json", {"plugins": {"unsafe@market": [None, {"scope": []}, {"scope": "user", "installPath": "../private"}]}})
        self.json_file(self.claude / "settings.json", {"enabledPlugins": {"unsafe@market": True}})
        result = self.inventory()
        self.assertEqual(result["skills"], [])
        self.assertFalse(result["complete"])
        self.assertGreaterEqual(len(result["warnings"]), 3)

    def test_plugin_id_stays_stable_when_cache_version_changes(self) -> None:
        def install(version: str) -> dict:
            plugin = self.plugin(self.root / "cache" / "active" / version, name="active")
            self.json_file(self.claude / "plugins" / "installed_plugins.json", {"plugins": {"active@market": [{"scope": "user", "installPath": str(plugin)}]}})
            return self.inventory()["skills"][0]
        self.json_file(self.claude / "settings.json", {"enabledPlugins": {"active@market": True}})
        first = install("1.0")
        self.choose("review", first)
        second = install("2.0")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.inventory()["conflicts"], [])
        self.assertEqual(resolve_skill(self.state, "review", **self.options)["resolution"]["status"], "selected")

    def test_project_ancestry_stops_at_git_root_and_without_git_at_requested_root(self) -> None:
        child = self.project / "child"
        child.mkdir()
        self.skill(self.root / ".claude" / "skills", "outside")
        self.skill(self.project / ".claude" / "skills", "parent-skill")
        self.skill(child / ".claude" / "skills", "child-skill")
        self.assertEqual({item["name"] for item in self.inventory(project_root=child)["skills"]}, {"child-skill"})
        (self.project / ".git").mkdir()
        self.assertEqual({item["name"] for item in self.inventory(project_root=child)["skills"]}, {"parent-skill", "child-skill"})

    def test_nested_project_without_git_discovers_nearest_parent_skills_and_enabled_plugin(self) -> None:
        child = self.project / "departments" / "reports"
        child.mkdir(parents=True)
        self.skill(self.project / ".claude" / "skills", "report")
        self.skill(self.root / ".claude" / "skills", "unrelated-ancestor")
        plugin = self.plugin(self.root / "cache" / "department" / "1.0", name="department")
        self.json_file(self.claude / "plugins" / "installed_plugins.json", {"plugins": {"department@market": [{"scope": "project", "installPath": str(plugin), "projectPath": str(self.project)}]}})
        self.json_file(self.project / ".claude" / "settings.json", {"enabledPlugins": {"department@market": True}})
        parent = self.inventory(project_root=self.project)
        report = next(item for item in parent["skills"] if item["name"] == "report")
        self.choose("report", report, project_root=self.project)
        before = (self.state / "config" / "skill-preferences.json").read_bytes()
        nested = self.inventory(project_root=child)
        self.assertEqual({item["name"] for item in nested["skills"]}, {"report", "review"})
        self.assertEqual(next(item for item in nested["skills"] if item["name"] == "review")["origin"], "department@market")
        self.assertEqual(resolve_skill(self.state, "report", project_root=child, **self.options)["resolution"]["status"], "selected")
        self.assertEqual((self.state / "config" / "skill-preferences.json").read_bytes(), before)

    def test_global_config_and_home_claude_are_not_discovered_as_project_roots(self) -> None:
        global_claude = self.root / ".claude"
        self.skill(global_claude / "skills", "global-helper")
        nested = self.inventory(project_root=self.project, claude_root=global_claude)
        self.assertEqual([(item["name"], item["source"]) for item in nested["skills"]], [("global-helper", "user")])
        with patch("company_agent.skill_registry.Path.home", return_value=self.root):
            home_result = self.inventory(project_root=self.project)
        self.assertEqual(home_result["skills"], [])

    def test_linked_ancestor_claude_is_not_a_no_git_project_boundary(self) -> None:
        child = self.project / "child"
        child.mkdir()
        external = self.root / "outside-claude"
        self.skill(external / "skills", "external")
        self.directory_link(self.project / ".claude", external)
        result = self.inventory(project_root=child)
        self.assertEqual(result["skills"], [])
        self.assertFalse(result["complete"])

    def test_project_selection_overrides_default_and_isolates_siblings(self) -> None:
        plugin, user, company = self.overlaps()
        child = self.project / "child"
        child.mkdir()
        sibling = self.root / "sibling"
        sibling.mkdir()
        self.choose("review", user, plugin_root=plugin)
        self.choose("review", company, project_root=self.project, plugin_root=plugin)
        for project, expected in ((self.project, company), (child, company), (sibling, user)):
            resolved = resolve_skill(self.state, "review", project_root=project, plugin_root=plugin, **self.options)
            self.assertEqual(resolved["resolution"]["selectedId"], expected["id"])
        reset_skill_preferences(self.state, project_root=self.project, name="review")
        resolved = resolve_skill(self.state, "review", project_root=child, plugin_root=plugin, **self.options)
        self.assertEqual(resolved["resolution"]["selectedId"], user["id"])

    def test_nearest_configured_project_scope_and_reset_do_not_touch_other_projects(self) -> None:
        plugin, user, company = self.overlaps()
        child = self.project / "child"
        child.mkdir()
        self.choose("review", user, plugin_root=plugin)
        self.choose("review", company, project_root=self.project, plugin_root=plugin)
        self.choose("review", user, project_root=child, plugin_root=plugin)
        self.assertEqual(resolve_skill(self.state, "review", project_root=child, plugin_root=plugin, **self.options)["resolution"]["selectedId"], user["id"])
        reset_skill_preferences(self.state, project_root=child)
        self.assertEqual(resolve_skill(self.state, "review", project_root=child, plugin_root=plugin, **self.options)["resolution"]["selectedId"], company["id"])
        reset_skill_preferences(self.state)
        self.assertEqual(resolve_skill(self.state, "review", project_root=self.project, plugin_root=plugin, **self.options)["resolution"]["selectedId"], company["id"])
        self.assertEqual(resolve_skill(self.state, "review", plugin_root=plugin, **self.options)["resolution"]["status"], "unresolved")

    def test_explicit_order_only_selects_unique_source_and_explicit_choice_beats_order(self) -> None:
        plugin, user, company = self.overlaps()
        self.assertEqual(self.inventory(plugin_root=plugin)["conflicts"][0]["resolution"]["status"], "unresolved")
        set_skill_source_order(self.state, ["company", "user"])
        self.assertEqual(self.inventory(plugin_root=plugin)["conflicts"][0]["resolution"]["selectedId"], company["id"])
        self.choose("review", user, plugin_root=plugin)
        self.assertEqual(self.inventory(plugin_root=plugin)["conflicts"][0]["resolution"]["selectedId"], user["id"])
        self.skill(self.claude / "skills", "alias", name="review")
        reset_skill_preferences(self.state, name="review")
        set_skill_source_order(self.state, ["user", "company"])
        self.assertEqual(self.inventory(plugin_root=plugin)["conflicts"][0]["resolution"]["status"], "unresolved")

    def test_stale_choice_does_not_fall_back_to_single_remaining_candidate_or_source_order(self) -> None:
        plugin, user, company = self.overlaps()
        self.choose("review", company, plugin_root=plugin)
        set_skill_source_order(self.state, ["user"])
        resolved = resolve_skill(self.state, "review", **self.options)
        self.assertEqual(resolved["resolution"]["status"], "stale-choice")
        self.assertNotEqual(resolved["resolution"]["selectedId"], user["id"])
        self.assertTrue(resolved["warnings"])
        self.assertTrue(resolved["complete"])
        self.assertEqual(search_skills(self.state, "review", **self.options)["skills"], [])

    def test_search_only_returns_recommended_candidates_and_reports_ambiguity(self) -> None:
        plugin, user, company = self.overlaps()
        ambiguous = search_skills(self.state, "review", plugin_root=plugin, **self.options)
        self.assertEqual(ambiguous["skills"], [])
        self.assertEqual(len(ambiguous["conflicts"]), 1)
        self.choose("review", company, plugin_root=plugin)
        selected = search_skills(self.state, "review", plugin_root=plugin, **self.options)
        self.assertEqual([item["id"] for item in selected["skills"]], [company["id"]])

    def test_natural_language_search_matches_any_keyword_and_ranks_name_first(self) -> None:
        self.skill(self.claude / "skills", "보고서", description="문서")
        self.skill(self.claude / "skills", "helper", description="보고서 생성")
        self.skill(self.claude / "skills", "unrelated", description="테스트")
        result = search_skills(self.state, "보고서 작성해줘", **self.options)
        self.assertEqual([item["name"] for item in result["skills"]], ["보고서", "helper"])

    def test_history_preserves_exact_previous_bytes_and_noop_does_not_rewrite(self) -> None:
        plugin, user, company = self.overlaps()
        self.choose("review", user, plugin_root=plugin)
        preferences = self.state / "config" / "skill-preferences.json"
        before = preferences.read_bytes()
        before_mtime = preferences.stat().st_mtime_ns
        self.choose("review", user, plugin_root=plugin)
        self.assertEqual(preferences.stat().st_mtime_ns, before_mtime)
        self.assertFalse((preferences.parent / "skill-preferences-history").exists())
        self.choose("review", company, plugin_root=plugin)
        history = list((preferences.parent / "skill-preferences-history").glob("*.json"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].read_bytes(), before)
        self.assertNotEqual(preferences.read_bytes(), before)

    def test_invalid_preference_json_schema_and_traversal_are_preserved(self) -> None:
        file = self.state / "config" / "skill-preferences.json"
        malformed = [
            "{not JSON, SECRET MUST NOT LEAK}",
            '{"schemaVersion":1,"schemaVersion":1,"defaults":{"sourceOrder":[],"skills":{}},"projects":{}}',
            json.dumps({"schemaVersion": 2, "defaults": {"sourceOrder": [], "skills": {}}, "projects": {}}),
            json.dumps({"schemaVersion": True, "defaults": {"sourceOrder": [], "skills": {}}, "projects": {}}),
            json.dumps({"schemaVersion": 1, "defaults": {"sourceOrder": [], "skills": {"../escape": "user:" + "a" * 24}}, "projects": {}}),
            json.dumps({"schemaVersion": 1, "defaults": {"sourceOrder": [], "skills": {}}, "projects": {"../escape": {"projectRoot": "../escape", "skills": {}}}}),
        ]
        file.parent.mkdir(parents=True)
        for raw in malformed:
            with self.subTest(raw=raw[:40]):
                file.write_text(raw, encoding="utf-8")
                before = file.read_bytes()
                with self.assertRaises(ValueError) as caught:
                    set_skill_source_order(self.state, ["personal"])
                self.assertNotIn("SECRET MUST NOT LEAK", str(caught.exception))
                self.assertEqual(file.read_bytes(), before)
                self.assertFalse((file.parent / "skill-preferences-history").exists())

    def test_unsupported_state_rejects_preferences_without_writing(self) -> None:
        self.json_file(self.state / "state-format.json", {"schemaVersion": 99})
        with self.assertRaises(ValueError):
            set_skill_source_order(self.state, ["personal"])
        self.assertFalse((self.state / "config").exists())

    def test_untrusted_manifest_cannot_escape_and_malformed_metadata_warns(self) -> None:
        outside = self.skill(self.root / "private", "secret")
        plugin = self.plugin(self.root / "plugin")
        self.json_file(plugin / ".claude-plugin" / "plugin.json", {"name": "company-agent", "skills": ["../private", str(outside)]})
        bad = self.claude / "skills" / "bad" / "SKILL.md"
        bad.parent.mkdir(parents=True)
        bad.write_bytes(b"\xff\xfe\xff")
        result = self.inventory(plugin_root=plugin)
        self.assertEqual([item["name"] for item in result["skills"]], ["review"])
        self.assertTrue(result["warnings"])
        self.assertFalse(result["complete"])
        self.assertNotIn(str(outside), [item["path"] for item in result["skills"]])

    def test_common_yaml_folded_description_and_nested_metadata_are_supported(self) -> None:
        file = self.skill(self.claude / "skills", "fallback")
        file.write_text("---\nname: review\ndescription: >-\n  Review Python changes\n  with a careful audit.\nmetadata:\n  author: Nobody\nallowed-tools: [Read, Grep]\n---\nDo not print this body\n", encoding="utf-8")
        result = self.inventory()["skills"][0]
        self.assertEqual(result["name"], "review")
        self.assertEqual(result["description"], "Review Python changes with a careful audit.")
        self.assertNotIn("Nobody", str(result))

    def test_symlink_skill_is_skipped_and_scan_continues(self) -> None:
        external = self.skill(self.root / "private", "external")
        self.skill(self.claude / "skills", "z-valid")
        link = self.claude / "skills" / "a-linked"
        self.directory_link(link, external.parent)
        result = self.inventory()
        self.assertEqual([item["name"] for item in result["skills"]], ["z-valid"])
        self.assertTrue(any("reparse" in item for item in result["warnings"]))

    def test_symlink_state_ancestor_is_rejected_before_directory_creation(self) -> None:
        target = self.root / "outside"
        target.mkdir()
        link = self.root / "link"
        self.directory_link(link, target)
        with self.assertRaises(ValueError):
            set_skill_source_order(link / "state", ["personal"])
        self.assertFalse((target / "state").exists())

    def test_symlink_history_is_rejected_before_preferences_change(self) -> None:
        set_skill_source_order(self.state, ["personal"])
        file = self.state / "config" / "skill-preferences.json"
        before = file.read_bytes()
        target = self.root / "outside"
        target.mkdir()
        self.directory_link(file.parent / "skill-preferences-history", target)
        with self.assertRaises(ValueError):
            set_skill_source_order(self.state, ["company"])
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(list(target.iterdir()), [])

    def test_invalid_candidate_name_and_order_do_not_create_state(self) -> None:
        for order in (["personal", "personal"], ["unknown"], "company", [1]):
            with self.subTest(order=order), self.assertRaises(ValueError):
                set_skill_source_order(self.state, order)
        with self.assertRaises(ValueError):
            set_skill_preference(self.state, "../escape", "user:" + "a" * 24, **self.options)
        with self.assertRaises(ValueError):
            set_skill_preference(self.state, "review", "user:" + "a" * 24, **self.options)
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
