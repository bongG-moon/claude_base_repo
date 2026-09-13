"""Language/compatibility contracts, not proof of every model's output language."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
sys.path.insert(0, str(PLUGIN / "scripts"))

from company_agent import project_harness as factory
from company_agent.completion_feedback import present_stop_feedback
from company_agent.frontmatter import parse_frontmatter_text
from company_agent.native_runtime import runtime_context, worker_runtime_input
from company_agent.paths import ensure_user_layout
from company_agent.state import _failure_message
from company_agent.user_language import KOREAN_DEFAULT_RULE


class KoreanDefaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.state = self.root / "state"
        ensure_user_layout(self.state)
        self.env = patch.dict(os.environ, {"COMPANY_AGENT_USER_STATE": str(self.state)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.spec = {"name": "korean", "goal": "주간보고 작성", "pattern": "pipeline",
                     "workflow": [{"id": "write", "task": "보고서 작성", "tier": "MEDIUM"}],
                     "successCriteria": ["원본 수치 보존"]}

    def seed_v1(self):
        spec = factory._spec(self.spec)
        files = factory._render(spec, 1)
        hashes = {}
        for relative, text in files.items():
            target = self.project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
            hashes[relative] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        manifest = {"schemaVersion": 1, "generatorVersion": 1, "spec": spec, "files": hashes}
        path = self.project / factory.MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return {p: (self.project / p).read_bytes() for p in files}

    def test_default_in_runtime_english_source_and_scoped_language_exception(self):
        context = json.loads(runtime_context(PLUGIN, self.project, "English report source material"))["company_agent_runtime"]
        self.assertIn(KOREAN_DEFAULT_RULE, context["instructions"])
        for concept in ("질문 제목", "선택지", "추천 이유", "최종 결과", "영어 입력자료", "요청한 범위", "API/JSON 키"):
            self.assertIn(concept, KOREAN_DEFAULT_RULE)
        main = (PLUGIN / "skills/company-agent/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Default to Korean", main)
        self.assertIn("AskUserQuestion headers/labels/descriptions", main)
        self.assertIn("only that deliverable, not the surrounding chat", main)
        self.assertLessEqual(len(main.splitlines()), 180)

    def test_all_owned_workers_receive_policy_without_model_or_scope_changes(self):
        for tier, model in (("small", "haiku"), ("medium", "sonnet"), ("large", "opus")):
            with self.subTest(tier=tier):
                metadata, body = parse_frontmatter_text((PLUGIN / f"agents/{tier}-worker.md").read_text(encoding="utf-8"))
                self.assertEqual(model, metadata["model"])
                self.assertIn("기본 한국어", body)
                original = {"subagent_type": f"company-agent:{tier}-worker", "prompt": "User explicitly requested an English email only.", "model": model}
                with patch("company_agent.native_runtime._skill_routing", return_value=([], {})):
                    result = worker_runtime_input(PLUGIN, self.project, {"session_id": "test", "tool_input": original})["hookSpecificOutput"]
                self.assertNotIn("permissionDecision", result)
                updated = result["updatedInput"]
                self.assertEqual(model, updated["model"])
                self.assertTrue(updated["prompt"].startswith(original["prompt"]))
                self.assertIn(KOREAN_DEFAULT_RULE, updated["prompt"])

    def test_common_menu_descriptions_are_korean_without_renaming_skills(self):
        files = [*PLUGIN.glob("skills/*/SKILL.md"), *PLUGIN.glob("commands/*.md"), *PLUGIN.glob("agents/*.md")]
        self.assertEqual(17, len(files))
        for path in files:
            with self.subTest(path=path):
                metadata, _ = parse_frontmatter_text(path.read_text(encoding="utf-8"))
                self.assertRegex(metadata["description"], r"[가-힣]")
                if "name" in metadata:
                    self.assertRegex(metadata["name"], r"^[a-z0-9-]+$")

    def test_generated_project_all_stages_have_korean_policy(self):
        result = factory.apply_project_harness(self.project, self.spec)
        self.assertTrue(result["ok"])
        manifest = json.loads((self.project / factory.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(2, manifest["generatorVersion"])
        for relative in manifest["files"]:
            self.assertIn("기본 한국어", (self.project / relative).read_text(encoding="utf-8"))
        self.assertTrue(factory.validate_project_harness(self.project)["ok"])

    def test_v1_remains_readable_and_explicit_update_backs_up_owned_files(self):
        before = self.seed_v1()
        self.assertTrue(factory.validate_project_harness(self.project)["ok"])
        self.assertIsNotNone(factory.inspect_project(self.project)["existingSpec"])
        self.assertEqual(before, {p: (self.project / p).read_bytes() for p in before})
        result = factory.apply_project_harness(self.project, self.spec)
        self.assertTrue(result["ok"])
        backup = self.project / result["backup"]
        for relative, content in before.items():
            self.assertEqual(content, (backup / relative).read_bytes())
        self.assertEqual([], factory.apply_project_harness(self.project, self.spec)["changedFiles"])

    def test_v1_hand_edited_project_is_not_overwritten_for_language_upgrade(self):
        self.seed_v1()
        target = self.project / factory.RULE
        target.write_text("사용자의 기존 프로젝트 규칙", encoding="utf-8")
        result = factory.apply_project_harness(self.project, self.spec)
        self.assertFalse(result["ok"])
        self.assertEqual("사용자의 기존 프로젝트 규칙", target.read_text(encoding="utf-8"))
        self.assertEqual(1, json.loads((self.project / factory.MANIFEST).read_text(encoding="utf-8"))["generatorVersion"])

    def test_visible_verification_failures_stay_honest_in_korean(self):
        for kind in ("same-failure", "budget"):
            raw = _failure_message(kind)
            rendered = present_stop_feedback(raw)
            self.assertIn("검증을 통과하지 못했", rendered["systemMessage"])
            self.assertNotIn("Verification", rendered["systemMessage"])
            self.assertIn("Verification", raw["systemMessage"])
            self.assertNotIn("decision", rendered)


if __name__ == "__main__":
    unittest.main()
