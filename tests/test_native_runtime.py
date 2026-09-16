from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
SCRIPTS = PLUGIN / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.cli import main as cli_main  # noqa: E402
from company_agent.frontmatter import dump_frontmatter  # noqa: E402
from company_agent.native_runtime import (  # noqa: E402
    MAX_HOOK_CONTEXT_CHARS, MAX_RUNTIME_CONTEXT_CHARS, bounded_prompt_context,
    cli_command, configure_runtime, resolve_registration, runtime_context, session_start,
)
from company_agent.paths import atomic_write_json, atomic_write_text, load_json  # noqa: E402
from company_agent.state import begin_turn, load_session, mark_verified, record_activity, stop_decision  # noqa: E402


class NativeRuntimeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "한글 native test"
        self.root.mkdir()
        self.registrations = self.root / "registrations"
        self.base = self.root / "corporate"
        self.state = self.root / "user-state"
        self.project = self.root / "project"
        self.project.mkdir()
        self.base.mkdir()
        atomic_write_json(self.base / "pack.json", {"version": "test"})
        atomic_write_text(self.base / "terms" / "wip.md", dump_frontmatter(
            {"kind": "term", "id": "term.wip", "title": "재공", "aliases": ["WIP"],
             "domain": "manufacturing", "owner": "제조팀", "status": "active"},
            "# 재공\n\n생산 공정 안에 있는 수량.",
        ))
        self.env_patch = patch.dict(os.environ, {
            "COMPANY_AGENT_USER_STATE": str(self.state),
            "COMPANY_AGENT_KNOWLEDGE_BASE": str(self.base),
            "COMPANY_AGENT_SCOPE": "User",
            "COMPANY_AGENT_PYTHON": sys.executable,
        })
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.temp.cleanup()

    def register(self, key: str, scope: str, project: Path | None = None, enabled: bool = True, **fields) -> dict:
        record = {"schemaVersion": 1, "scope": scope, "enabled": enabled,
                  "userStateRoot": str(self.root / (key + "-state")),
                  "knowledgeBaseRoot": str(self.base),
                  "projectRoot": str(project) if project else None, **fields}
        directory = self.registrations / "user" if scope == "User" else self.registrations / "projects" / key
        atomic_write_json(directory / "company-agent-install.json", record)
        return record


class NativeRuntimeTests(NativeRuntimeTestBase):
    def test_unrelated_personal_skill_is_not_injected_even_when_only_one_exists(self) -> None:
        file = self.state / "personal-root" / ".claude" / "skills" / "chart" / "SKILL.md"
        atomic_write_text(file, dump_frontmatter({"name": "chart", "description": "차트 그리기"}, "# private procedure"))
        for prompt in ("", "메일 작성"):
            context = json.loads(runtime_context(PLUGIN, self.project, prompt))["company_agent_runtime"]
            self.assertEqual([], context["personalSkills"])

    def test_knowledge_cards_bound_untrusted_metadata_and_preserve_overlay_discovery(self) -> None:
        from unittest.mock import patch
        huge = {"id": "term.test", "title": "조회" * 20_000, "kind": "term", "source": "corporate",
                "path": "C:/knowledge/test.md", "aliases": ["MUST-NOT-INJECT" * 50_000],
                "overlays": [{"path": "secret-metadata" * 50_000}]}
        with patch("company_agent.native_runtime.search_catalog", return_value=[huge] * 3):
            text = runtime_context(PLUGIN, self.project, "조회")
        self.assertLessEqual(len(text), MAX_RUNTIME_CONTEXT_CHARS)
        cards = json.loads(text)["company_agent_runtime"]["knowledgeMatches"]
        self.assertTrue(cards[0]["hasOverlays"])
        self.assertNotIn("MUST-NOT-INJECT", text)
        self.assertNotIn("secret-metadata", text)

    def test_over_budget_route_drops_optional_memory_without_breaking_json(self) -> None:
        route = json.dumps({"company_agent_route": {"tier": "LARGE"}, "company_agent_session_id": "test",
                            "company_agent_personal_memory_context": "\\\"" * 10_000})
        context = bounded_prompt_context(route, runtime_context(PLUGIN, self.project))
        self.assertLessEqual(len(context), MAX_HOOK_CONTEXT_CHARS)
        first, second = context.split("\n", 1)
        self.assertEqual("LARGE", json.loads(first)["company_agent_route"]["tier"])
        self.assertEqual("test", json.loads(first)["company_agent_session_id"])
        self.assertIn("company_agent_runtime", json.loads(second))

    def test_long_windows_runtime_paths_keep_commands_and_context_budget(self) -> None:
        # No filesystem access: realistic cached-plugin/state path lengths with
        # quoted spaces/Korean names and the maximum discovery-card workload.
        for length in (140, 225):
            prefix = Path("C:/Users/2069026/AppData/Local")
            plugin = prefix / ("plugin-cache-" + "p" * (length - 50)) / "company agent"
            state = prefix / ("personal-state-" + "s" * (length - 55)) / "개인 상태"
            project = prefix / ("projects-" + "w" * (length - 45))
            cards = [{"name": f"report-{n}", "source": "personal", "path": str(state / f"skills/{n}/SKILL.md"),
                      "description": "보고서 작성 " * 40} for n in range(8)]
            with self.subTest(length=length), patch.dict(os.environ, {
                "COMPANY_AGENT_USER_STATE": str(state), "COMPANY_AGENT_KNOWLEDGE_BASE": str(prefix / "knowledge")}), \
                 patch("company_agent.native_runtime._skill_routing", return_value=(cards, {})), \
                 patch("company_agent.native_runtime._knowledge_matches", return_value=[]):
                text = runtime_context(plugin, project, "보고서")
                context = json.loads(text)["company_agent_runtime"]
                self.assertLessEqual(len(text), MAX_RUNTIME_CONTEXT_CHARS)
                self.assertNotIn("contextStatus", context)
                self.assertEqual(cli_command(plugin), context["cliCommand"])
                self.assertEqual(str(state), context["stateRoot"])
                metadata = shlex.split(context["metadataCommand"])
                self.assertEqual(Path(sys.executable), Path(metadata[0]))
                self.assertEqual(plugin / "scripts" / "harness_cli.py", Path(metadata[2]))
                route = json.dumps({"company_agent_route": {"tier": "MEDIUM"},
                                    "company_agent_personal_memory_context": "한글" * 5000})
                combined = bounded_prompt_context(route, text)
                self.assertLessEqual(len(combined), MAX_HOOK_CONTEXT_CHARS)
                self.assertEqual(context, json.loads(combined.split("\n", 1)[1])["company_agent_runtime"])

    def test_compaction_rehydrates_verification_without_resetting_retry_budget(self) -> None:
        begin_turn("compact-test", "LARGE", True, (), self.state)
        record_activity({"session_id": "compact-test", "tool_name": "Write"}, self.state)
        mark_verified("compact-test", "fail", "a check failed", self.state)
        stop_decision({"session_id": "compact-test"}, self.state)
        before = load_session("compact-test", self.state)
        with patch.dict(os.environ, {"CLAUDE_ENV_FILE": ""}):
            result = session_start(PLUGIN, self.project, session_id="compact-test", source="compact")
        context = json.loads(result["hookSpecificOutput"]["additionalContext"])["company_agent_runtime"]
        self.assertTrue(context["afterCompact"])
        self.assertEqual("fail", context["sessionState"]["verificationStatus"])
        self.assertEqual(1, context["sessionState"]["stopRetryCount"])
        self.assertEqual(1, context["sessionState"]["sameFailureCount"])
        self.assertEqual("LARGE", context["sessionState"]["modelTier"])
        after = load_session("compact-test", self.state)
        # Compaction invalidates only the derived Skill-read receipts. Existing
        # verification, learning and retry obligations must remain byte-equivalent.
        self.assertFalse(after.pop("skillWorkflow")["indexRead"])
        self.assertEqual(before, after)
        self.assertNotIn("a check failed", json.dumps(context))

    def test_skill_stat_failure_does_not_hide_other_relevant_skills(self) -> None:
        from company_agent.native_runtime import _personal_skills
        directory = self.state / "personal-root" / ".claude" / "skills"
        bad = directory / "broken" / "SKILL.md"
        good = directory / "working" / "SKILL.md"
        for path in (bad, good):
            atomic_write_text(path, dump_frontmatter({"name": path.parent.name, "description": "차트 작성"}, "# body"))
        original = Path.stat
        def stat_with_race(path, *args, **kwargs):
            if path == bad:
                raise FileNotFoundError("removed during discovery")
            return original(path, *args, **kwargs)
        with patch.object(Path, "stat", stat_with_race):
            found = _personal_skills(self.state, "차트")
        self.assertEqual(["working"], [item["name"] for item in found])

    def test_scope_uses_nearest_project_then_user_and_ignores_disabled(self) -> None:
        user = self.register("user", "User")
        project = self.register("project", "Project", self.project)
        nested_root = self.project / "nested"
        nested = self.register("nested", "Project", nested_root)
        self.assertEqual(nested, resolve_registration(self.registrations, nested_root / "src"))
        self.assertEqual(project, resolve_registration(self.registrations, self.project / "other"))
        self.assertEqual(user, resolve_registration(self.registrations, self.root / "unrelated"))
        self.register("nested", "Project", nested_root, enabled=False)
        self.assertEqual(project, resolve_registration(self.registrations, nested_root))
        self.register("project", "Project", self.project, enabled=False)
        self.assertEqual(user, resolve_registration(self.registrations, self.project))
        self.register("user", "User", enabled=False)
        self.assertIsNone(resolve_registration(self.registrations, self.project))

    def test_project_only_is_inactive_outside_and_project_text_cannot_enable_it(self) -> None:
        self.register("project", "Project", self.project)
        unrelated = self.root / "unrelated"
        atomic_write_json(unrelated / "company-agent-install.json", {
            "schemaVersion": 1, "scope": "User", "enabled": True,
            "userStateRoot": "untrusted-project-state",
        })
        self.assertIsNone(resolve_registration(self.registrations, unrelated))

    def test_configure_runtime_uses_registered_state_and_respects_disabled_scope(self) -> None:
        plugin = self.root / "plugin"
        record = self.register("project", "Project", self.project)
        atomic_write_json(plugin / "company-agent-install.json", {
            "registrationsRoot": str(self.registrations), "knowledgeBaseRoot": str(self.base),
        })
        self.assertTrue(configure_runtime(plugin, self.project))
        self.assertEqual(record["userStateRoot"], os.environ["COMPANY_AGENT_USER_STATE"])
        self.assertEqual("Project", os.environ["COMPANY_AGENT_SCOPE"])
        self.assertFalse(configure_runtime(plugin, self.root / "outside"))

    def test_legacy_launcher_can_supply_explicit_state_without_install_metadata(self) -> None:
        self.assertTrue(configure_runtime(PLUGIN, self.project))
        self.assertEqual(str(self.state), os.environ["COMPANY_AGENT_USER_STATE"])

    def test_stale_project_install_record_falls_back_to_enabled_native_user_install(self) -> None:
        profile = self.root / "claude-profile"
        plugin_id = "company-agent@company-agent-local"
        common = {"claudeConfigRoot": str(profile), "claudeConfigDirOverride": True, "pluginId": plugin_id}
        user = self.register("user", "User", nativeClaudeScope="user", **common)
        project = self.register("project", "Project", self.project, nativeClaudeScope="local", **common)
        atomic_write_json(profile / "settings.json", {"enabledPlugins": {plugin_id: True}})
        atomic_write_json(self.project / ".claude" / "settings.local.json", {"enabledPlugins": {plugin_id: True}})
        inventory = profile / "plugins" / "installed_plugins.json"
        user_entry = {"scope": "user", "installPath": str(self.root / "cached-plugin")}
        project_entry = {"scope": "local", "projectPath": str(self.project)}
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(profile)}):
            atomic_write_json(inventory, {"plugins": {plugin_id: [user_entry]}})
            self.assertEqual(user, resolve_registration(self.registrations, self.project))
            atomic_write_json(inventory, {"plugins": {plugin_id: [user_entry, project_entry]}})
            self.assertEqual(project, resolve_registration(self.registrations, self.project))
            atomic_write_json(self.project / ".claude" / "settings.local.json", {"enabledPlugins": {plugin_id: False}})
            self.assertEqual(user, resolve_registration(self.registrations, self.project))

    def test_profile_mismatch_does_not_switch_profile_or_personal_state(self) -> None:
        plugin = self.root / "plugin"
        original_profile = self.root / "active-profile"
        other_profile = self.root / "other-profile"
        self.register("user", "User", nativeClaudeScope="user",
                      claudeConfigRoot=str(other_profile), claudeConfigDirOverride=True)
        atomic_write_json(plugin / "company-agent-install.json", {"registrationsRoot": str(self.registrations)})
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(original_profile)}):
            self.assertFalse(configure_runtime(plugin, self.project))
            self.assertEqual(str(original_profile), os.environ["CLAUDE_CONFIG_DIR"])
            self.assertEqual(str(self.state), os.environ["COMPANY_AGENT_USER_STATE"])

    def test_default_absent_and_explicit_config_directory_identity_are_preserved(self) -> None:
        plugin = self.root / "plugin"
        atomic_write_json(plugin / "company-agent-install.json", {"registrationsRoot": str(self.registrations)})
        for explicit in (False, True):
            with self.subTest(explicit=explicit), patch.dict(os.environ, {}):
                profile = self.root / "explicit-profile" if explicit else Path.home() / ".claude"
                self.register("user", "User", claudeConfigRoot=str(profile), claudeConfigDirOverride=explicit)
                if explicit:
                    os.environ["CLAUDE_CONFIG_DIR"] = str(profile)
                else:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                self.assertTrue(configure_runtime(plugin, self.project))
                if explicit:
                    self.assertEqual(str(profile), os.environ["CLAUDE_CONFIG_DIR"])
                else:
                    self.assertNotIn("CLAUDE_CONFIG_DIR", os.environ)

    def test_init_and_doctor_inherit_aliases_without_email_or_model_id_values(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli_main(["init-user", "--display-name", "홍길동"])
        self.assertEqual(0, code)
        config = load_json(self.state / "config" / "user.json")
        self.assertEqual("홍길동", config["display_name"])
        self.assertEqual("", config["user_email"])
        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "DO-NOT-PRINT-SECRET"}):
            for name in ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL"):
                os.environ.pop(name, None)
            output = io.StringIO()
            with patch("company_agent.cli.shutil.which", return_value=sys.executable), contextlib.redirect_stdout(output):
                code = cli_main(["doctor"])
        self.assertEqual(0, code, output.getvalue())
        report = json.loads(output.getvalue())
        self.assertTrue(report["ok"])
        for key, alias in (("smallModel", "haiku"), ("mediumModel", "sonnet"), ("largeModel", "opus")):
            self.assertTrue(report["checks"][key]["ok"])
            self.assertEqual(alias, report["checks"][key]["alias"])
            self.assertFalse(report["checks"][key]["liveVerified"])
        self.assertNotIn("DO-NOT-PRINT-SECRET", output.getvalue())

    def test_session_context_indexes_knowledge_and_bounds_matching_skill_metadata(self) -> None:
        skill_root = self.state / "personal-root" / ".claude" / "skills"
        for index in range(20):
            name = f"personal-{index:02}"
            atomic_write_text(skill_root / name / "SKILL.md", dump_frontmatter(
                {"name": name, "description": "재공 분석 " + "설명" * 600},
                "RAW-SKILL-BODY-MUST-NOT-BE-INJECTED " * 100,
            ))
        atomic_write_text(skill_root / "specific-report" / "SKILL.md", dump_frontmatter(
            {"name": "specific-report", "description": "특정월보고서 엑셀 양식 작성"}, "# 작업 지침",
        ))
        with patch.dict(os.environ, {"CLAUDE_ENV_FILE": ""}):
            started = session_start(PLUGIN, self.project)
        self.assertEqual("SessionStart", started["hookSpecificOutput"]["hookEventName"])
        self.assertTrue((self.state / "knowledge" / "generated-index" / "catalog.json").exists())
        serialized = runtime_context(PLUGIN, self.project, "재공 분석")
        context = json.loads(serialized)["company_agent_runtime"]
        self.assertLessEqual(len(context["personalSkills"]), 8)
        self.assertTrue(context["knowledgeMatches"])
        self.assertLess(len(serialized), 16000)
        self.assertNotIn("RAW-SKILL-BODY", serialized)
        exact = json.loads(runtime_context(PLUGIN, self.project, "specific-report"))["company_agent_runtime"]
        self.assertEqual([], exact["personalSkills"])
        catalog=Path(exact['skillSelection']['catalog']['path']).read_text(encoding='utf-8')
        self.assertIn('specific-report',catalog)
        self.assertNotIn('RAW-SKILL-BODY',catalog)
        self.assertIn('skillIndex', exact["instructions"])

    def test_budget_trims_extra_skill_cards_before_losing_only_knowledge_card(self):
        from company_agent.native_runtime import _encode_runtime
        data = {"instructions": "i" * 200, "knowledgeMatches": [{"id": "knowledge", "title": "k" * 80}],
                "preferredSkills": [], "personalSkills": [{"name": str(n), "description": "s" * 180} for n in range(3)],
                "skillSelection": {"conflicts": []}}
        with patch("company_agent.native_runtime.MAX_RUNTIME_CONTEXT_CHARS", 800):
            text = _encode_runtime(data)
        self.assertLessEqual(len(text), 800)
        runtime = json.loads(text)["company_agent_runtime"]
        self.assertEqual("knowledge", runtime["knowledgeMatches"][0]["id"])
        self.assertTrue(runtime["personalSkills"])


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Native Windows PowerShell required")
class NativePowerShellTests(NativeRuntimeTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.plugin = self.root / "plugin copy"
        shutil.copytree(PLUGIN, self.plugin, ignore=shutil.ignore_patterns("__pycache__", "runtime"))
        self.record = self.register("project", "Project", self.project)
        atomic_write_json(self.plugin / "company-agent-install.json", {
            "registrationsRoot": str(self.registrations), "knowledgeBaseRoot": str(self.base),
        })

    def run_wrapper(self, arguments: list[str], payload: dict | None = None, cwd: Path | None = None,
                    env_overrides: dict[str, str | None] | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("CLAUDE_ENV_FILE", None)
        env["COMPANY_AGENT_PYTHON"] = sys.executable
        for key, value in (env_overrides or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(
            [shutil.which("powershell.exe"), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(self.plugin / "scripts" / "Invoke-CompanyAgent.ps1"), *arguments],
            cwd=cwd or self.project, env=env,
            input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            text=True, encoding="utf-8", capture_output=True, timeout=30, check=False,
        )

    def test_native_permission_request_allows_only_registered_metadata_command(self) -> None:
        payload = {"session_id": "permission-fixture", "cwd": str(self.project)}
        started = self.run_wrapper(["-Mode", "Hook", "-Event", "SessionStart"], payload)
        self.assertEqual(0, started.returncode, started.stderr)
        runtime = json.loads(json.loads(started.stdout)["hookSpecificOutput"]["additionalContext"])["company_agent_runtime"]
        self.assertEqual(self.record["userStateRoot"], runtime["stateRoot"])
        base_command = runtime["metadataCommand"]
        for operation in ("doctor", "mail-capabilities"):
            command = f'{base_command} business {operation} --state-root "{runtime["stateRoot"]}"'
            result = self.run_wrapper(["-Mode", "Hook", "-Event", "PermissionRequest"], {
                **payload, "tool_name": "Bash", "tool_input": {"command": command,
                "description": "PRIVATE-PERMISSION-DETAIL-MUST-NOT-ECHO"},
            })
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stderr)
            self.assertEqual({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}},
                             json.loads(result.stdout))
            self.assertNotIn("PRIVATE-", result.stdout)
            self.assertNotIn(runtime["stateRoot"], result.stdout)

        # Execute only business doctor. Do not touch an actual Outlook instance.
        command = shlex.split(base_command) + ["business", "doctor", "--state-root", runtime["stateRoot"]]
        env = dict(os.environ, COMPANY_AGENT_USER_STATE=str(self.root / "wrong-state"),
                   PYTHONIOENCODING="cp949:strict", PYTHONUTF8="0")
        completed = subprocess.run(command, cwd=self.project, env=env, capture_output=True, timeout=30)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(b"", completed.stderr)
        doctor = json.loads(completed.stdout)
        self.assertEqual("diagnostic_only", doctor["status"])
        self.assertEqual("connection_not_tested", doctor["outlook"]["status"])
        self.assertFalse((self.root / "wrong-state").exists())

    def test_native_hooks_refresh_catalog_without_business_verification_obligation(self) -> None:
        session = "catalog-only-session"
        payload = {"session_id": session, "cwd": str(self.project)}
        isolated_claude = self.root / "isolated-claude"
        overrides = {"CLAUDE_CONFIG_DIR": str(isolated_claude)}
        def context(event, **extra):
            result = self.run_wrapper(["-Mode", "Hook", "-Event", event], {**payload, **extra}, env_overrides=overrides)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stderr)
            envelope = json.loads(result.stdout)
            # Native prompt output contains route JSON followed by runtime JSON.
            text = envelope["hookSpecificOutput"]["additionalContext"].splitlines()[-1]
            return json.loads(text)["company_agent_runtime"]
        started = context("SessionStart")
        first = started["skillSelection"]["catalog"]
        self.assertEqual("ready", first["status"])
        file = Path(first["path"])
        before = file.stat().st_mtime_ns
        unchanged = context("UserPromptSubmit", prompt="사용 가능한 기능만 설명해줘")
        self.assertEqual(first["revision"], unchanged["skillSelection"]["catalog"]["revision"])
        self.assertEqual(before, file.stat().st_mtime_ns)
        incoming = isolated_claude / "skills" / "deck" / "SKILL.md"
        atomic_write_text(incoming, dump_frontmatter({"name": "deck", "description": "Editable PowerPoint presentations"}, "PRIVATE-BODY"))
        added = context("UserPromptSubmit", prompt="발표자료를 만들 수 있는지 설명해줘")
        self.assertNotEqual(first["revision"], added["skillSelection"]["catalog"]["revision"])
        self.assertIn("Editable PowerPoint", file.read_text(encoding="utf-8"))
        self.assertNotIn("PRIVATE-BODY", file.read_text(encoding="utf-8"))
        incoming.unlink()
        deleted = context("UserPromptSubmit", prompt="목록만 확인해줘")
        self.assertEqual(first["revision"], deleted["skillSelection"]["catalog"]["revision"])
        self.assertEqual(0, load_session(session, Path(self.record["userStateRoot"]))["mutationCount"])

    def test_native_permission_request_keeps_untrusted_body_and_malformed_requests_pending(self) -> None:
        payload = {"session_id": "permission-deny-fixture", "cwd": str(self.project), "tool_name": "Bash"}
        command = f'"{sys.executable}" -B "{self.plugin / "scripts" / "harness_cli.py"}"'
        cases = [
            {"command": f'{command} business mail-read --spec "{self.root / "PRIVATE-body.json"}"'},
            {"command": f'{command} business mail-search --spec "{self.root / "PRIVATE-search.json"}"'},
            {"command": f'{command} business doctor --state-root "{self.root / "PRIVATE-foreign-state"}"'},
            {"command": f'{command} business doctor; echo PRIVATE-COMPOUND'},
            {"command": 'company-agent business doctor'},
            {"command": f'"{self.root / "PRIVATE-python.exe"}" "{self.plugin / "scripts" / "harness_cli.py"}" business doctor'},
            {"command": None}, {"command": ["PRIVATE-MALFORMED"]}, {},
        ]
        for tool_input in cases:
            with self.subTest(tool_input=tool_input):
                result = self.run_wrapper(["-Mode", "Hook", "-Event", "PermissionRequest"], {**payload, "tool_input": tool_input})
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", result.stderr)
                self.assertEqual({}, json.loads(result.stdout))
                self.assertNotIn("PRIVATE-", result.stdout)

    def test_native_wrapper_reads_korean_stdin_and_cli_verification_survives_hook(self) -> None:
        session = "native-session"
        payload = {"session_id": session, "cwd": str(self.project)}
        started = self.run_wrapper(["-Mode", "Hook", "-Event", "SessionStart"], payload)
        self.assertEqual(0, started.returncode, started.stderr)
        self.assertEqual("", started.stderr)
        context = json.loads(json.loads(started.stdout)["hookSpecificOutput"]["additionalContext"])["company_agent_runtime"]
        self.assertEqual(self.record["userStateRoot"], context["stateRoot"])
        self.assertEqual("Project", context["scope"])
        routed = self.run_wrapper(["-Mode", "Hook", "-Event", "UserPromptSubmit"], {
            **payload, "prompt": "코드 파일을 수정해줘. DO-NOT-STORE-RAW-PROMPT",
        })
        self.assertEqual(0, routed.returncode, routed.stderr)
        self.assertEqual("UserPromptSubmit", json.loads(routed.stdout)["hookSpecificOutput"]["hookEventName"])
        self.assertNotIn("DO-NOT-STORE-RAW-PROMPT", routed.stdout)
        activity = self.run_wrapper(["-Mode", "Hook", "-Event", "PostToolUse"], {
            **payload, "tool_name": "Write", "tool_input": {"content": "DO-NOT-STORE-CODE"},
        })
        self.assertEqual(0, activity.returncode, activity.stderr)
        verified = self.run_wrapper(["-Mode", "Cli", "session", "verify", "--session", session,
                                     "--status", "pass", "--summary", "한글 검증 성공"])
        self.assertEqual(0, verified.returncode, verified.stderr)
        self.assertEqual("한글 검증 성공", json.loads(verified.stdout)["verification"]["summary"])
        command = cli_command(self.plugin) + f' session verify --session {session} --status pass --summary "한글 검증 성공"'
        activity = self.run_wrapper(["-Mode", "Hook", "-Event", "PostToolUse"], {
            **payload, "tool_name": "PowerShell", "tool_input": {"command": command},
        })
        self.assertEqual(0, activity.returncode, activity.stderr)
        state = load_session(session, Path(self.record["userStateRoot"]))
        self.assertEqual("pass", state["verification"]["status"])
        stopped = self.run_wrapper(["-Mode", "Hook", "-Event", "Stop"], payload)
        self.assertEqual({}, json.loads(stopped.stdout))
        milestone = self.run_wrapper(["-Mode", "Cli", "work", "checkpoint", "--session", session,
                                      "--turn", state["turnId"], "--status", "complete", "--learn", "yes"])
        self.assertEqual(0, milestone.returncode, milestone.stderr)
        stopped = self.run_wrapper(["-Mode", "Hook", "-Event", "Stop"], payload)
        self.assertEqual("block", json.loads(stopped.stdout)["decision"])
        self.assertIn("업무 마무리", json.loads(stopped.stdout)["reason"])
        self.assertIn("completionGuide", context)
        self.assertTrue(Path(context["completionGuide"]).is_file())
        self.assertNotIn("learning review", json.loads(stopped.stdout)["reason"])
        self.assertLessEqual(len(json.loads(stopped.stdout)["reason"]), 100)
        turn_id = state["turnId"]
        spec_path = Path(self.record["userStateRoot"]) / "tmp" / f"learning-review-{turn_id}.json"
        atomic_write_json(spec_path, {"schemaVersion": 1, "taskType": "native-file-test", "outcome": "success",
                                     "summary": "한글 검증 결과를 확인함", "observations": [], "evaluations": []})
        staging = self.run_wrapper(["-Mode", "Hook", "-Event", "PostToolUse"], {
            **payload, "tool_name": "Write", "tool_input": {"file_path": str(spec_path), "content": "DO-NOT-STORE-JSON-INPUT"},
        })
        self.assertEqual(0, staging.returncode, staging.stderr)
        reviewed = self.run_wrapper(["-Mode", "Cli", "learning", "review", "--session", session,
                                     "--turn", turn_id, "--spec", str(spec_path)])
        self.assertEqual(0, reviewed.returncode, reviewed.stderr)
        self.assertEqual("skipped", json.loads(reviewed.stdout)["status"])
        self.assertFalse((Path(self.record["userStateRoot"]) / "learning" / "state.json").exists())
        review_command = cli_command(self.plugin) + f' learning review --session {session} --turn {turn_id} --spec "{spec_path}"'
        review_activity = self.run_wrapper(["-Mode", "Hook", "-Event", "PostToolUse"], {
            **payload, "tool_name": "PowerShell", "tool_input": {"command": review_command},
        })
        self.assertEqual(0, review_activity.returncode, review_activity.stderr)
        closed = self.run_wrapper(["-Mode", "Hook", "-Event", "Stop"], payload)
        self.assertEqual({}, json.loads(closed.stdout))
        state = load_session(session, Path(self.record["userStateRoot"]))
        self.assertEqual("complete", state["learningStatus"])
        self.assertEqual("pass", state["verification"]["status"])
        self.assertNotIn("DO-NOT-STORE", json.dumps(state))
        failed = self.run_wrapper(["-Mode", "Cli", "session", "verify", "--session", session,
                                   "--status", "fail", "--summary", "한글 검증 실패"])
        self.assertEqual(1, failed.returncode, failed.stderr)
        self.assertEqual("fail", json.loads(failed.stdout)["verification"]["status"])

    def test_native_wrapper_is_inactive_outside_registered_project(self) -> None:
        result = self.run_wrapper(["-Mode", "Hook", "-Event", "SessionStart"], {
            "session_id": "outside-session", "cwd": str(self.root),
        }, cwd=self.root)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({}, json.loads(result.stdout))

    def test_native_compact_source_never_reads_or_saves_transcript(self) -> None:
        result = self.run_wrapper(["-Mode", "Hook", "-Event", "SessionStart"], {
            "session_id": "after-compact", "cwd": str(self.project), "source": "compact",
            "transcript_path": "C:/must-not-be-opened/transcript.jsonl", "compact_summary": "DO-NOT-STORE-SUMMARY",
        })
        self.assertEqual(0, result.returncode, result.stderr)
        context = json.loads(json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])["company_agent_runtime"]
        self.assertTrue(context["afterCompact"])
        self.assertNotIn("DO-NOT-STORE-SUMMARY", result.stdout)

    def test_project_scoped_cli_does_not_initialize_outside_its_project(self) -> None:
        result = self.run_wrapper(["-Mode", "Cli", "init-user"], cwd=self.root)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.state / "config" / "user.json").exists())
        self.assertFalse((Path(self.record["userStateRoot"]) / "config" / "user.json").exists())

    def test_native_wrapper_uses_installer_pinned_python_without_python_on_path(self) -> None:
        metadata = load_json(self.plugin / "company-agent-install.json")
        metadata["pythonCommand"] = sys.executable
        atomic_write_json(self.plugin / "company-agent-install.json", metadata)
        powershell = Path(shutil.which("powershell.exe"))
        minimal_path = os.pathsep.join([str(powershell.parent), str(Path(os.environ["SystemRoot"]) / "System32")])
        result = self.run_wrapper(["-Mode", "Hook", "-Event", "SessionStart"], {
            "session_id": "pinned-runtime", "cwd": str(self.project),
        }, env_overrides={"COMPANY_AGENT_PYTHON": None, "PATH": minimal_path})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertEqual("SessionStart", json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"])


if __name__ == "__main__":
    unittest.main()
