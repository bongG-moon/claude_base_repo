"""Offline routing/continuation checks: never call the production HCP model."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
sys.path.insert(0, str(PLUGIN / "scripts"))
from company_agent import vision_routing as vision
import native_entry


def call(tool="Read", inputs=None, **extra):
    return {"tool_name": tool, "tool_input": inputs or {"file_path": r"C:\work\슬라이드.PNG"}, **extra}


class VisionRoutingTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"ANTHROPIC_CUSTOM_MODEL_OPTION": vision.VISION_MODEL})
        env.start()
        self.addCleanup(env.stop)

    def test_production_opt_in_uses_id_not_display_name(self):
        for env in ({}, {"ANTHROPIC_CUSTOM_MODEL_OPTION_NAME": "HCP Vision"},
                    {"ANTHROPIC_CUSTOM_MODEL_OPTION": "HCP Vision"},
                    {"ANTHROPIC_MODEL": "HCP-Big-Latest"}):
            self.assertFalse(vision.enabled(env))
        self.assertTrue(vision.enabled({"ANTHROPIC_CUSTOM_MODEL_OPTION": vision.VISION_MODEL}))

    def test_absent_model_keeps_existing_reads_and_mcp(self):
        with patch.dict(os.environ, {"ANTHROPIC_CUSTOM_MODEL_OPTION": ""}):
            self.assertEqual({}, vision.context())
            self.assertEqual({}, vision.preflight(call()))
            self.assertIsNone(vision.preflight(call("mcp__playwright__browser_take_screenshot")))
            result = vision.preflight(call("Agent", {"subagent_type": vision.VISION_AGENT, "prompt": "inspect"}))
            self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
            self.assertNotIn("updatedInput", result["hookSpecificOutput"])

    def test_text_read_fast_path_has_no_model_override(self):
        for file in ("SKILL.md", "draft.html", "data.csv", "picture.svg", "x.png.txt", "image.png/notes.md", "README"):
            with self.subTest(file=file):
                self.assertEqual({}, vision.preflight(call(inputs={"file_path": file})))
        self.assertEqual({}, vision.preflight({"tool_name": "Read", "tool_input": None}))

    def test_images_and_pdf_are_redirected_before_main_reads_them(self):
        for suffix in vision.IMAGE_SUFFIXES:
            result = vision.preflight(call(inputs={"file_path": "C:/work/test" + suffix}))
            self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
            self.assertIn(vision.VISION_AGENT, result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_child_identity_not_main_agent_option_is_required(self):
        self.assertEqual({}, vision.preflight(call(agent_type=vision.VISION_AGENT, agent_id="v1")))
        for extra in ({"agent_type": vision.VISION_AGENT}, {"agent_id": "w1"},
                      {"agent_type": "other:vision-worker", "agent_id": "v1"}):
            self.assertEqual("deny", vision.preflight(call(**extra))["hookSpecificOutput"]["permissionDecision"])

    def test_normal_worker_hands_off_without_recursive_delegation(self):
        payload = call(agent_type="company-agent:medium-worker", agent_id="worker1")
        self.assertIn("NEEDS_VISION", vision.preflight(payload)["hookSpecificOutput"]["permissionDecisionReason"])
        nested = call("Agent", {"subagent_type": vision.VISION_AGENT, "prompt": "inspect"}, agent_id="worker1")
        self.assertEqual("deny", vision.preflight(nested)["hookSpecificOutput"]["permissionDecision"])

    def test_known_captures_are_routed_but_text_snapshots_unchanged(self):
        for tool in vision.CAPTURE_TOOLS:
            self.assertEqual("deny", vision.preflight(call(tool))["hookSpecificOutput"]["permissionDecision"])
        for tool in ("mcp__playwright__browser_snapshot", "mcp__chrome-devtools__list_pages",
                     "mcp__local-computer-use__computer_inspect", "mcp__corp-db-read__query",
                     "mcp__unknown__take_screenshot"):
            self.assertIsNone(vision.preflight(call(tool)))
        # Mixed-output tools are not silently assumed image-free or rerouted.

    def test_vision_worker_is_observation_only_without_auto_allow(self):
        identity = {"agent_type": vision.VISION_AGENT, "agent_id": "v1"}
        for tool in ("Read", "mcp__chrome-devtools__take_screenshot", "mcp__local-computer-use__computer_inspect"):
            self.assertEqual({}, vision.preflight(call(tool, **identity)))
        for tool in ("Bash", "PowerShell", "Write", "Edit", "Skill", "AskUserQuestion",
                     "mcp__chrome-devtools__click", "mcp__local-computer-use__computer_run_task"):
            result = vision.preflight(call(tool, **identity))["hookSpecificOutput"]
            self.assertEqual("deny", result["permissionDecision"])
            self.assertNotIn("updatedInput", result)

    def test_real_local_computer_zoom_name_is_routed_and_supported(self):
        payload = call("mcp__local-computer-use__zoom", {"pid": 10, "window_id": 20})
        self.assertEqual("deny", vision.preflight(payload)["hookSpecificOutput"]["permissionDecision"])
        self.assertEqual({}, vision.preflight({**payload, "agent_type": vision.VISION_AGENT, "agent_id": "v1"}))
        lookalike = {**payload, "tool_name": "mcp__unrelated__zoom", "agent_type": vision.VISION_AGENT, "agent_id": "v1"}
        self.assertEqual("deny", vision.preflight(lookalike)["hookSpecificOutput"]["permissionDecision"])

    def test_dispatch_forces_exact_model_preserves_permissions_and_starts_fresh(self):
        for tool in ("Agent", "Task"):
            inputs = {"subagent_type": vision.VISION_AGENT, "prompt": "Inspect only slide 2", "model": "opus",
                      "description": "image check", "resume": "old-text-worker", "max_turns": 4}
            original = copy.deepcopy(inputs)
            result = vision.preflight(call(tool, inputs))["hookSpecificOutput"]
            updated = result["updatedInput"]
            self.assertNotIn("model", updated)  # exact ID is in the definition
            self.assertNotIn("resume", updated)
            self.assertNotIn("permissionDecision", result)
            self.assertEqual(4, updated["max_turns"])
            self.assertTrue(updated["prompt"].endswith(original["prompt"]))
            self.assertEqual(original, inputs)

    def test_unrelated_agents_are_untouched(self):
        for name in ("general-purpose", "company-agent:medium-worker", "other:vision-worker"):
            self.assertIsNone(vision.preflight(call("Agent", {"subagent_type": name, "model": "opus"})))

    def test_empty_vision_task_is_not_a_probe(self):
        for prompt in (None, "", "  "):
            result = vision.preflight(call("Agent", {"subagent_type": vision.VISION_AGENT, "prompt": prompt}))
            self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])

    def test_failure_is_unverified_without_retry_loop_or_raw_error_echo(self):
        payload = call("Agent", {"subagent_type": vision.VISION_AGENT}, error="secret gateway response")
        result = vision.result_context("PostToolUseFailure", payload)
        text = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("미검증", text)
        self.assertIn("반복", text)
        self.assertIn("검증 의무는 지우지", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("decision", result)

    def test_observation_result_does_not_persist_image_or_capture_as_mutation(self):
        payload = call(agent_type=vision.VISION_AGENT, agent_id="v1", tool_response={"type": "image", "data": "SECRET"})
        self.assertEqual({}, vision.result_context("PostToolUse", payload))
        self.assertIsNone(vision.result_context("Stop", payload))
        self.assertIsNone(vision.result_context("PostToolUseFailure", call("Bash")))

    def run_entry(self, payload, event="PreToolUse", *, active=True, scope_check=True):
        output = io.StringIO()
        with patch.object(sys, "argv", ["native_entry.py", "--event", event]), \
             patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
             patch.object(native_entry, "configure_runtime", return_value=active) as configure, \
             contextlib.redirect_stdout(output):
            self.assertEqual(0, native_entry.main())
        if scope_check:
            self.assertLessEqual(configure.call_count, 1)
        else:
            configure.assert_not_called()
        return json.loads(output.getvalue())

    def test_native_entry_fast_paths_do_not_scan_runtime_or_create_receipts(self):
        self.assertEqual({}, self.run_entry(call(inputs={"file_path": "plain.md"}), scope_check=False))
        self.assertEqual("deny", self.run_entry(call())["hookSpecificOutput"]["permissionDecision"])
        self.assertEqual({}, self.run_entry(call(agent_type=vision.VISION_AGENT, agent_id="v1")))
        result = self.run_entry(call("Agent", {"subagent_type": vision.VISION_AGENT, "prompt": "inspect"}))
        self.assertNotIn("model", result["hookSpecificOutput"]["updatedInput"])

    def test_inactive_project_keeps_image_calls_and_agents_unchanged(self):
        self.assertEqual({}, self.run_entry(call(), active=False))
        self.assertEqual({}, self.run_entry(call("Agent", {"subagent_type": vision.VISION_AGENT, "prompt": "inspect"}), active=False))

    def test_failed_vision_entry_does_not_enter_activity_or_stop_recovery(self):
        payload = call("Agent", {"subagent_type": vision.VISION_AGENT, "prompt": "inspect"})
        self.assertIn("미검증", self.run_entry(payload, "PostToolUseFailure")["hookSpecificOutput"]["additionalContext"])

    def test_offline_handoff_then_text_continuation_keeps_normal_model(self):
        # Host/model responses are fixtures. This proves routing, NOT image
        # understanding, real HCP availability or obedience by a weak LLM.
        normal_model = "HCP-Big-Latest"
        main_model_before = os.environ.get("ANTHROPIC_MODEL")
        request = call("Agent", {"subagent_type": vision.VISION_AGENT, "prompt": "slide-01.png에서 겹침 확인", "model": normal_model})
        routed = self.run_entry(request)["hookSpecificOutput"]["updatedInput"]
        self.assertNotIn("model", routed)
        self.assertEqual({}, self.run_entry(call(agent_type=vision.VISION_AGENT, agent_id="fixture-vision")))
        response = "[가상 검증 응답] 1장 제목 겹침 없음. 작은 각주 가독성은 미확인."
        self.run_entry({**request, "tool_response": {"content": response}}, "PostToolUse")
        followup = call("Agent", {"subagent_type": "company-agent:medium-worker", "prompt": response, "model": normal_model})
        self.assertIsNone(vision.preflight(followup))
        self.assertEqual(normal_model, followup["tool_input"]["model"])
        self.assertEqual(main_model_before, os.environ.get("ANTHROPIC_MODEL"))
        self.assertEqual({}, self.run_entry(call(inputs={"file_path": "next-task.md"})))

    def test_worker_runtime_contains_conditional_route_without_model_change(self):
        from company_agent.native_runtime import worker_runtime_input
        with patch.dict(os.environ, {"COMPANY_AGENT_USER_STATE": str(ROOT / ".smoke/vision-test-no-write-state")}), \
             patch("company_agent.native_runtime._skill_routing", return_value=([], {"status": "ready"})):
            result = worker_runtime_input(PLUGIN, ROOT, call("Agent", {
                "subagent_type": "company-agent:medium-worker", "prompt": "work", "model": "sonnet"}))
            updated = result["hookSpecificOutput"]["updatedInput"]
            self.assertEqual("sonnet", updated["model"])
            self.assertIn('"visionRouting":{"enabled":true', updated["prompt"])
            self.assertIn("NEEDS_VISION", updated["prompt"])

    def test_guidance_identity_changes_when_vision_configuration_changes(self):
        from company_agent.native_runtime import _prompt_guidance
        base = {"instructions": "", "skillExecution": {"mode": "reuse"}}
        inactive = _prompt_guidance(copy.deepcopy(base))
        active = {**base, "visionRouting": vision.context()}
        revision = _prompt_guidance(active)
        self.assertNotEqual(inactive, revision)
        self.assertIn("NEEDS_VISION", active["instructions"])

    def test_native_agent_and_hook_are_packaged(self):
        from company_agent.frontmatter import parse_frontmatter_text
        meta, body = parse_frontmatter_text((PLUGIN / "agents/vision-worker.md").read_text(encoding="utf-8"))
        self.assertEqual(vision.VISION_MODEL, meta["model"])
        self.assertIn("Agent", meta["disallowedTools"])
        for tool in vision.OBSERVATION_TOOLS:
            self.assertIn(tool, meta["tools"])
        self.assertIn("텍스트", body)
        hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        matcher = hooks["PreToolUse"][0]["matcher"]
        for name in ("Read", "Agent", "Task", "mcp__test__screenshot"):
            self.assertRegex(name, matcher)
        script = (PLUGIN / "scripts/Invoke-CompanyAgent.ps1").read_text(encoding="utf-8-sig")
        suffixes = re.search(r"\$isImageRead = .*?@\(([^)]+)\)", script).group(1)
        self.assertEqual(vision.IMAGE_SUFFIXES, set(re.findall(r"'(\.[a-z]+)'", suffixes)))

    @unittest.skipUnless(sys.platform == "win32", "PowerShell launcher on Windows")
    def test_real_powershell_text_read_fast_path_needs_no_runtime(self):
        result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(PLUGIN / "scripts/Invoke-CompanyAgent.ps1"), "-Mode", "Hook", "-Event", "PreToolUse"],
            input=json.dumps(call(inputs={"file_path": "plain.md"})), capture_output=True, text=True,
            encoding="utf-8", timeout=20, env={**os.environ, "COMPANY_AGENT_PYTHON": "does-not-exist"})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({}, json.loads(result.stdout))

    @unittest.skipUnless(sys.platform == "win32", "PowerShell launcher on Windows")
    def test_real_launcher_routes_image_without_opening_it_or_calling_model(self):
        # Only the hook is executed, not Claude/model/Read. The target need not
        # exist: routing happens before native permissions or opening the image.
        payload = call(inputs={"file_path": "C:/synthetic/한글이미지.png"})
        result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(PLUGIN / "scripts/Invoke-CompanyAgent.ps1"), "-Mode", "Hook", "-Event", "PreToolUse"],
            input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=30,
            env={**os.environ, "COMPANY_AGENT_USER_STATE": str(ROOT / ".smoke/vision-test-no-write-state"),
                 "COMPANY_AGENT_PYTHON": sys.executable})
        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual("deny", output["permissionDecision"])
        self.assertIn("[비전 인계]", output["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
