from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))

from company_agent import project_harness as factory  # noqa: E402
from company_agent.frontmatter import parse_frontmatter_text  # noqa: E402


class ProjectHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "my-project"
        self.project.mkdir()
        self.spec = {
            "name": "weekly", "goal": "검증된 주간 보고서를 작성한다.", "pattern": "pipeline",
            "workflow": [
                {"id": "collect", "task": "입력 자료의 기간을 확인한다.", "tier": "SMALL"},
                {"id": "compose", "task": "입력 근거로 요약을 작성한다.", "tier": "MEDIUM"},
            ],
            "successCriteria": ["각 수치에 원본 근거가 있다."],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_inspect_and_plan_are_read_only_and_do_not_run_project_commands(self) -> None:
        (self.project / "README.md").write_text("# Report", encoding="utf-8")
        (self.project / "package.json").write_text('{"scripts":{"postinstall":"do-not-run"}}', encoding="utf-8")
        original = sorted(str(item) for item in self.project.rglob("*"))
        inventory = factory.inspect_project(self.project)
        self.assertEqual(["javascript"], inventory["detectedStacks"])
        self.assertIn("README.md", inventory["documents"])
        self.assertTrue(factory.plan_project_harness(self.project, self.spec)["ok"])
        self.assertEqual(original, sorted(str(item) for item in self.project.rglob("*")))

    def test_create_has_valid_frontmatter_models_references_and_is_idempotent(self) -> None:
        result = factory.apply_project_harness(self.project, self.spec)
        self.assertTrue(result["ok"])
        self.assertTrue(factory.validate_project_harness(self.project)["ok"])
        expected = {"collect": "haiku", "compose": "sonnet", "architect": "opus", "reviewer": "sonnet"}
        for stage, model in expected.items():
            path = self.project / ".claude/agents" / f"company-project-weekly-{stage}.md"
            metadata, _ = parse_frontmatter_text(path.read_text(encoding="utf-8"))
            self.assertEqual(model, metadata["model"])
            for skill in metadata["skills"]:
                self.assertTrue((self.project / ".claude/skills" / skill / "SKILL.md").exists())
        for skill in (self.project / ".claude/skills").glob("*/SKILL.md"):
            metadata, _ = parse_frontmatter_text(skill.read_text(encoding="utf-8"))
            self.assertLessEqual(len(metadata["name"]), 64)
        before = {str(item): item.stat().st_mtime_ns for item in self.project.rglob("*") if item.is_file()}
        rerun = factory.apply_project_harness(self.project, self.spec)
        after = {str(item): item.stat().st_mtime_ns for item in self.project.rglob("*") if item.is_file()}
        self.assertEqual([], rerun["changedFiles"])
        self.assertEqual(before, after)

    def test_all_patterns_have_distinct_orchestration_and_no_experimental_team_requirement(self) -> None:
        bodies = []
        for pattern in factory.PATTERNS:
            spec = {**self.spec, "pattern": pattern}
            plan = factory.plan_project_harness(self.project, spec)
            body = next(item["content"] for item in plan["files"] if item["path"] == ".claude/skills/company-project-weekly/SKILL.md")
            self.assertIn(factory.PATTERNS[pattern], body)
            self.assertIn("24 total Agent invocations", body)
            self.assertNotIn("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1", body)
            bodies.append(body)
        self.assertEqual(6, len(set(bodies)))

    def test_existing_unowned_file_blocks_even_when_replace_owned_is_selected(self) -> None:
        target = self.project / ".claude/agents/company-project-weekly-collect.md"
        target.parent.mkdir(parents=True)
        target.write_text("my original instructions", encoding="utf-8")
        self.spec["conflictStrategy"] = "replace-owned"
        result = factory.apply_project_harness(self.project, self.spec)
        self.assertFalse(result["ok"])
        self.assertIn("unowned", result["conflicts"][0]["reason"])
        self.assertEqual("my original instructions", target.read_text(encoding="utf-8"))
        self.assertFalse((self.project / factory.MANIFEST).exists())

    def test_hand_edited_owned_file_is_preserved_then_explicitly_backed_up(self) -> None:
        factory.apply_project_harness(self.project, self.spec)
        relative = ".claude/agents/company-project-weekly-collect.md"
        target = self.project / relative
        target.write_text("user improvement", encoding="utf-8")
        self.assertFalse(factory.apply_project_harness(self.project, self.spec)["ok"])
        self.assertEqual("user improvement", target.read_text(encoding="utf-8"))
        self.spec["conflictStrategy"] = "replace-owned"
        result = factory.apply_project_harness(self.project, self.spec)
        self.assertTrue(result["ok"])
        self.assertEqual("user improvement", (Path(result["backup"]) / relative).read_text(encoding="utf-8"))
        self.assertTrue(factory.validate_project_harness(self.project)["ok"])

    def test_removing_stage_removes_only_owned_files_and_preserves_unrelated_state(self) -> None:
        factory.apply_project_harness(self.project, self.spec)
        unrelated = self.project / ".claude/agents/manual.md"
        unrelated.write_text("untouched", encoding="utf-8")
        claude_md = self.project / "CLAUDE.md"
        claude_md.write_text("existing project policy", encoding="utf-8")
        self.spec["workflow"] = self.spec["workflow"][:1]
        result = factory.apply_project_harness(self.project, self.spec)
        self.assertTrue(result["ok"])
        removed = ".claude/agents/company-project-weekly-compose.md"
        self.assertFalse((self.project / removed).exists())
        self.assertTrue((Path(result["backup"]) / removed).exists())
        self.assertEqual("untouched", unrelated.read_text(encoding="utf-8"))
        self.assertEqual("existing project policy", claude_md.read_text(encoding="utf-8"))

    def test_renaming_harness_deletes_old_owned_assets_and_repoints_rule(self) -> None:
        factory.apply_project_harness(self.project, self.spec)
        self.spec["name"] = "monthly"
        result = factory.apply_project_harness(self.project, self.spec)
        self.assertTrue(result["ok"])
        self.assertFalse((self.project / ".claude/skills/company-project-weekly/SKILL.md").exists())
        self.assertIn("company-project-monthly", (self.project / factory.RULE).read_text(encoding="utf-8"))

    def test_late_apply_failure_restores_previous_files_and_manifest(self) -> None:
        factory.apply_project_harness(self.project, self.spec)
        previous_manifest = (self.project / factory.MANIFEST).read_bytes()
        previous = {name: (self.project / name).read_bytes() for name in json.loads(previous_manifest)["files"]}
        self.spec["goal"] = "개선된 보고서를 작성한다."
        self.spec["workflow"][0]["task"] = "입력 자료의 기간과 필수 열을 확인한다."
        real_write = factory._write_bytes
        failed = False

        def fail_once(path: Path, data: bytes) -> None:
            nonlocal failed
            if not failed and "backups" not in path.parts and path.name == "contract.md":
                failed = True
                raise OSError("injected disk failure")
            real_write(path, data)

        with mock.patch.object(factory, "_write_bytes", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "injected disk failure"):
                factory.apply_project_harness(self.project, self.spec)
        self.assertTrue(failed)
        self.assertEqual(previous_manifest, (self.project / factory.MANIFEST).read_bytes())
        for relative, content in previous.items():
            self.assertEqual(content, (self.project / relative).read_bytes(), relative)
        self.assertFalse((self.project / factory.LOCK).exists())
        self.assertTrue(factory.validate_project_harness(self.project)["ok"])

    def test_failed_first_install_removes_new_files(self) -> None:
        real_write = factory._write_bytes
        writes = 0

        def fail_second(path: Path, data: bytes) -> None:
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("injected write error")
            real_write(path, data)

        with mock.patch.object(factory, "_write_bytes", side_effect=fail_second):
            with self.assertRaises(OSError):
                factory.apply_project_harness(self.project, self.spec)
        self.assertEqual([], [item for item in self.project.rglob("*") if item.is_file()])

    def test_malformed_specs_fail_without_writing(self) -> None:
        bad = [[], {**self.spec, "name": "../escape"}, {**self.spec, "maxRetries": True},
               {**self.spec, "maxRetries": 4}, {**self.spec, "workflow": []},
               {**self.spec, "workflwo": []}, {**self.spec, "successCriteria": []},
               {**self.spec, "workflow": [{"id": "reviewer", "task": "duplicate"}]},
               {**self.spec, "workflow": [{"id": "run", "task": "x", "tier": "unknown"}]},
               {**self.spec, "knowledgePaths": ["../outside"]}]
        for spec in bad:
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    factory.apply_project_harness(self.project, spec)
        self.assertEqual([], list(self.project.iterdir()))

    def test_relative_project_and_missing_or_external_knowledge_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute"):
            factory.inspect_project(Path("relative-project"))
        for path in ["missing.md", "C:/secret.txt", "/secret.txt", "docs/../../secret.txt"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                factory.plan_project_harness(self.project, {**self.spec, "knowledgePaths": [path]})

    def test_manifest_cannot_claim_an_unrelated_file(self) -> None:
        factory.apply_project_harness(self.project, self.spec)
        path = self.project / factory.MANIFEST
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"]["important.txt"] = "0" * 64
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ownership"):
            factory.plan_project_harness(self.project, self.spec)
        self.assertFalse(factory.validate_project_harness(self.project)["ok"])

    def test_v2_manifest_remains_valid_and_upgrades_without_losing_user_files(self) -> None:
        spec = factory._spec(self.spec)
        files = factory._render(spec, 2)
        for name, body in files.items():
            target = self.project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body.encode('utf-8'))
        manifest = {'schemaVersion':1, 'generatorVersion':2, 'spec':spec,
                    'files':{name:factory._digest(body.encode('utf-8')) for name, body in files.items()}}
        (self.project / factory.MANIFEST).parent.mkdir(parents=True, exist_ok=True)
        (self.project / factory.MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
        personal = self.project / 'MY_NOTES.md'
        personal.write_text('개인 자료 그대로', encoding='utf-8')
        self.assertTrue(factory.validate_project_harness(self.project)['ok'])
        self.assertTrue(factory.apply_project_harness(self.project, self.spec)['ok'])
        self.assertEqual(3, json.loads((self.project / factory.MANIFEST).read_text(encoding='utf-8'))['generatorVersion'])
        self.assertEqual('개인 자료 그대로', personal.read_text(encoding='utf-8'))
        contract = (self.project / '.claude/skills/company-project-weekly/references/contract.md').read_text(encoding='utf-8')
        self.assertIn('별도 팀팩이 아닙니다', contract)
        self.assertTrue(factory.validate_project_harness(self.project)['ok'])

    def test_lock_prevents_concurrent_apply(self) -> None:
        lock = self.project / factory.LOCK
        lock.parent.mkdir(parents=True)
        lock.touch()
        with self.assertRaisesRegex(ValueError, "another factory operation"):
            factory.apply_project_harness(self.project, self.spec)
        self.assertTrue(lock.exists())

    def test_junction_or_symlink_cannot_redirect_writes_outside_project(self) -> None:
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        link = self.project / ".claude"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError, "symlink/junction/reparse"):
                factory.apply_project_harness(self.project, self.spec)
            self.assertEqual([], list(outside.iterdir()))
        finally:
            if os.name == "nt":
                link.rmdir()
            else:
                link.unlink()

    def test_validate_detects_missing_and_edited_files_and_deleted_knowledge(self) -> None:
        doc = self.project / "terms.md"
        doc.write_text("table definitions", encoding="utf-8")
        spec = copy.deepcopy(self.spec)
        spec["knowledgePaths"] = ["terms.md"]
        factory.apply_project_harness(self.project, spec)
        doc.unlink()
        (self.project / factory.RULE).write_text("changed", encoding="utf-8")
        (self.project / ".claude/agents/company-project-weekly-reviewer.md").unlink()
        result = factory.validate_project_harness(self.project)
        self.assertFalse(result["ok"])
        self.assertEqual(3, len(result["issues"]))

    def test_real_cli_business_and_coding_projects_generate_domain_specific_contracts(self) -> None:
        scenarios = [
            {
                "folder": "주간 실적 분석", "name": "weekly", "pattern": "pipeline",
                "document": "실적 집계는 제품코드와 기준주차로 구분한다. 원본 CSV와 결과를 대조한다.",
                "goal": "주간 실적 CSV를 검증하고 제품별 변동 요약을 작성한다.",
                "task": "실적.csv에서 제품코드와 기준주차의 누락을 확인하고 집계 결과를 원본과 대조한다.",
                "criterion": "보고서의 제품별 합계가 실적.csv 원본 합계와 일치한다.",
            },
            {
                "folder": "내부 API 개발", "name": "api-check", "pattern": "producer-reviewer",
                "document": "FastAPI 프로젝트다. GET /health는 status 문자열을 반환하며 소비자는 그 필드를 사용한다.",
                "goal": "내부 FastAPI의 생산자와 소비자 응답 계약을 검증하며 기능을 개발한다.",
                "task": "GET /health 구현과 소비자의 status 문자열 기대값을 함께 확인하고 해당 pytest 검증을 수행한다.",
                "criterion": "GET /health의 status 필드와 소비자 테스트의 자료형이 일치한다.",
            },
        ]
        script = ROOT / "company-agent-plugin/scripts/harness_cli.py"
        for scenario in scenarios:
            with self.subTest(project=scenario["folder"]):
                project = Path(self.temp.name) / scenario["folder"]
                project.mkdir()
                (project / "README.md").write_text(scenario["document"], encoding="utf-8")
                spec = {"name": scenario["name"], "goal": scenario["goal"], "pattern": scenario["pattern"],
                        "workflow": [{"id": "execute", "task": scenario["task"], "tier": "MEDIUM"}],
                        "successCriteria": [scenario["criterion"]], "knowledgePaths": ["README.md"]}
                spec_path = Path(self.temp.name) / (scenario["name"] + ".json")
                spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
                for operation in ("inspect", "plan", "apply", "validate"):
                    command = [sys.executable, "-X", "utf8", str(script), "harness", operation, "--project", str(project)]
                    if operation in {"plan", "apply"}:
                        command += ["--spec", str(spec_path)]
                    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
                    self.assertEqual(0, process.returncode, process.stderr)
                    result = json.loads(process.stdout)
                    self.assertTrue(result["ok"])
                generated = (project / f".claude/skills/company-project-{scenario['name']}/SKILL.md").read_text(encoding="utf-8")
                self.assertIn(scenario["task"], generated)
                self.assertIn(scenario["criterion"], generated)
                self.assertEqual(scenario["document"], (project / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
