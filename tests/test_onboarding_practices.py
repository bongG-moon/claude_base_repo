"""Exercise the manual's examples without touching an installed user profile.

These checks prove local storage/factory contracts, not model adherence or
Claude Code's live CLAUDE.md loading. Those remain learner-observed checks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))

from company_agent import asset_factory as assets
from company_agent import project_harness as harness
from company_agent.frontmatter import parse_frontmatter_text, dump_frontmatter
from company_agent.memory import search_memory, upsert_memory
from company_agent.skill_registry import resolve_skill
from company_agent.workspace_api import WorkspaceService


def example(name: str) -> str:
    text = (ROOT / "docs/ONBOARDING_COURSE.md").read_text(encoding="utf-8")
    matches = re.findall(
        rf"<!-- onboarding-example: {re.escape(name)} -->\n```\w+\n(.*?)\n```",
        text, re.S,
    )
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one course example: {name}")
    return matches[0] + "\n"


class OnboardingPracticeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="company-onboarding-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "personal-state"
        self.claude = self.root / "isolated-claude"
        self.plugin = self.root / "empty-plugin"
        self.project = self.root / "practice-A"
        self.peer = self.root / "practice-B"
        for folder in [self.claude, self.plugin, self.project, self.peer]:
            folder.mkdir()
        patcher = mock.patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.claude),
            "COMPANY_AGENT_USER_STATE": str(self.state),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def _skill_spec(self):
        metadata, body = parse_frontmatter_text(example("personal-skill"))
        return {"type": "skill", "name": metadata["name"],
                "description": metadata["description"], "instructions": body}

    def _resolve(self, name, state=None):
        return resolve_skill(state or self.state, name, project_root=self.project,
                             claude_root=self.claude, plugin_root=self.plugin)

    def _tool_spec(self):
        cases = json.loads(example("tool-cases"))
        cases += [
            {"input": {"targets": [1] * 13, "actuals": [1] * 13}, "error": True},
            {"input": {"targets": [1000001], "actuals": [1]}, "error": True},
            {"input": {"targets": [1.5], "actuals": [1]}, "error": True},
        ]
        return {"type": "mcp", "format": "platform-tools-v1", "name": "onboarding-achievement",
                "description": "가상 월간 실적의 합계와 달성률 계산 연습",
                "tools_code": example("tool-code"), "reviewed_capabilities": ["third-party-import"],
                "tool_tests": [{"tool": "achievement", "arguments": c["input"],
                                **({"is_error": True} if c.get("error") else {"expect": {"json": c["expected"]}})}
                               for c in cases]}

    def _input(self, payload):
        file = self.root / "practice-input.json"
        file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return file

    def test_shared_instruction_and_personal_memory_have_independent_storage(self):
        team = self.project / "CLAUDE.md"
        team.write_text(example("team-claude"), encoding="utf-8")
        # Explicit sharing of only the fictional project file, not user state.
        other_team = self.peer / "CLAUDE.md"
        other_team.write_bytes(team.read_bytes())
        original = team.read_bytes()
        preference = {"id": "memory.preference.onboarding-order", "kind": "preference",
                      "title": "온보딩 요약 순서",
                      "body": "온보딩 월간 보고는 핵심 결론, 수치, 확인할 사항 순서로 설명한다."}
        stored = upsert_memory(preference, self.state)
        self.assertEqual(preference["id"], search_memory(self.state, "온보딩 요약 순서")[0]["id"])
        # A different personal root does not inherit memory from a shared file.
        self.assertEqual([], search_memory(self.root / "other-personal-state", "온보딩 요약 순서"))
        before = stored.read_bytes()
        search_memory(self.state, "이번에는 수치부터 설명")
        self.assertEqual(before, stored.read_bytes())
        upsert_memory({**preference, "status": "inactive"}, self.state)
        self.assertEqual([], search_memory(self.state, "온보딩 요약 순서"))
        self.assertTrue(stored.is_file())  # inactive is not deletion
        self.assertEqual(original, team.read_bytes())
        self.assertEqual(original, other_team.read_bytes())

    def test_common_knowledge_is_shared_by_explicit_base_not_by_personal_save(self):
        base = self.root/'common-knowledge'
        base.mkdir()
        file = base/'company.term.achievement.md'
        file.write_text(dump_frontmatter({'id':'company.term.achievement','kind':'term',
            'title':'가상 달성률','status':'active'},'목표 300건, 실적 330건의 달성률은 110%다.'),encoding='utf-8')
        original = file.read_bytes()
        record = {'scope':'User','userStateRoot':str(self.state),'claudeConfigRoot':str(self.claude),'knowledgeBaseRoot':str(base)}
        mine = WorkspaceService(record,self.project,self.plugin)
        peer = WorkspaceService({**record,'userStateRoot':str(self.root/'peer-state')},self.peer,self.plugin)
        self.assertEqual(mine.snapshot('shared-memory')['knowledge']['items'],peer.snapshot('shared-memory')['knowledge']['items'])
        mine.apply(mine.plan({'kind':'memory','storageScope':'personal','title':'온보딩 요약 순서','body':'결론을 먼저 설명한다.'}))
        self.assertEqual(1,len(mine.snapshot('my-memory')['memory']['items']))
        self.assertEqual([],peer.snapshot('my-memory')['memory']['items'])
        self.assertEqual([],mine.snapshot('my-memory')['knowledge']['items'])
        self.assertEqual(original,file.read_bytes())
        self.assertFalse((self.root/'peer-state').exists())

    def test_personal_skill_example_is_valid_discoverable_and_not_shared_implicitly(self):
        spec = self._skill_spec()
        path = assets.create_asset(spec, self.state)
        self.assertTrue(assets.validate_asset(path)["ok"])
        self.assertEqual(self.state / "personal-root/.claude/skills" / spec["name"], path)
        registry = json.loads((self.state / "assets/registry.json").read_text(encoding="utf-8"))
        self.assertEqual("active", registry["assets"][0]["status"])
        selection = self._resolve(spec["name"])
        self.assertEqual("available", selection["resolution"]["status"])
        self.assertEqual(str(path / "SKILL.md"), selection["candidates"][0]["path"])
        self.assertEqual([], self._resolve(spec["name"], self.root / "other-state")["candidates"])
        self.assertEqual([], list(self.plugin.rglob("*")))

    def test_skill_name_collision_preserves_existing_personal_file(self):
        spec = self._skill_spec()
        previous = self.claude / "skills" / spec["name"] / "SKILL.md"
        previous.parent.mkdir(parents=True)
        previous.write_text(example("personal-skill"), encoding="utf-8")
        old = previous.read_bytes()
        with self.assertRaises(ValueError):
            assets.create_asset(spec, self.state)
        self.assertEqual(old, previous.read_bytes())
        self.assertFalse((self.state / "personal-root/.claude/skills" / spec["name"]).exists())

    def test_tool_examples_require_receipt_then_pass_normal_boundary_and_error_cases(self):
        from company_agent.skill_tool_dependencies import check_skill_dependencies
        spec = self._tool_spec()
        path = assets.create_asset(spec, self.state)
        self.assertEqual("candidate", json.loads((path / "asset.json").read_text(encoding="utf-8"))["status"])
        self.assertTrue(assets.validate_asset(path)["ok"])
        with self.assertRaises(ValueError):
            assets.activate_mcp(self.state, spec["name"], "no-receipt")
        receipt = assets.validate_mcp_runtime(self.state, spec["name"], timeout=20)
        details = json.loads(receipt.read_text(encoding="utf-8"))["details"]
        self.assertEqual(12, details["businessTestCount"])
        self.assertEqual(["achievement"], details["businessTools"])
        assets.activate_mcp(self.state, spec["name"], receipt)
        report = {"type": "skill", "name": "practice-achievement-report", "description": "가상 합계 설명",
                  "instructions": "계산 도구를 호출하고 결과를 설명한다.",
                  "tool_dependencies": [{"server": spec["name"], "tools": ["achievement"]}]}
        skill = assets.create_asset(report, self.state)
        self.assertEqual("available", self._resolve(report["name"])["resolution"]["status"])
        self.assertTrue(check_skill_dependencies(self.state, report["name"])["ok"])
        self.assertIn("asset check-skill", (skill / "SKILL.md").read_text(encoding="utf-8"))
        # Configuration registration and the live Claude session were not exercised here.
        self.assertFalse(check_skill_dependencies(self.state, report["name"], self.project)["ok"])
        source = path / "src/mcp/tools.py"
        source.write_text(source.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        self.assertFalse(check_skill_dependencies(self.state, report["name"])["ok"])
        with self.assertRaisesRegex(ValueError, "changed after validation"):
            assets.activate_mcp(self.state, spec["name"], receipt)

    def test_project_harness_plan_and_apply_preserve_claude_and_other_project(self):
        team = self.project / "CLAUDE.md"
        team.write_text(example("team-claude"), encoding="utf-8")
        other = self.peer / "CLAUDE.md"
        other.write_text("# 가상 프로젝트 B\n결과 제목은 [연습 B].\n", encoding="utf-8")
        original, peer_before = team.read_bytes(), other.read_bytes()
        spec = {"name": "onboarding-report", "goal": "가상 월간 보고를 확인하고 작성한다.",
                "pattern": "pipeline",
                "workflow": [{"id": "read", "task": "가상 수치와 자료 범위를 확인한다.", "tier": "SMALL"},
                             {"id": "compose", "task": "확인한 수치로 초안을 작성한다.", "tier": "MEDIUM"}],
                "successCriteria": ["목표 300, 실적 330, 달성률 110%와 일치한다.",
                                    "자료에 없는 증가 원인을 추정하지 않는다."]}
        self.assertTrue(harness.plan_project_harness(self.project, spec)["ok"])
        self.assertEqual(["CLAUDE.md"], sorted(p.name for p in self.project.iterdir()))
        self.assertTrue(harness.apply_project_harness(self.project, spec)["ok"])
        self.assertTrue(harness.validate_project_harness(self.project)["ok"])
        self.assertEqual(original, team.read_bytes())
        self.assertEqual(peer_before, other.read_bytes())
        self.assertEqual(["CLAUDE.md"], sorted(p.name for p in self.peer.iterdir()))


if __name__ == "__main__":
    unittest.main()
