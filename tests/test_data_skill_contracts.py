"""Validate shipped data-skill instructions against real file and CLI contracts.

No model, personal profile, Office, or mailbox is opened by these checks.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import shlex
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))
from company_agent.asset_factory import create_asset
from company_agent.cli import build_parser
from company_agent.skill_lifecycle import inspect_skill


class DataSkillContracts(unittest.TestCase):
    def test_conditional_references_resolve_in_each_distribution(self):
        names = ("excel-to-pipeline", "work-context-catalog", "outlook-assistant",
                 "file-organizer", "asset-factory", "platform-mcp-builder")
        checked = 0
        for distribution in ("company-agent-plugin/skills", "standalone-skills"):
            boundary = (ROOT / distribution).resolve()
            for name in names:
                entry = boundary / name / "SKILL.md"
                if not entry.is_file():
                    continue
                text = entry.read_text(encoding="utf-8-sig")
                for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                    if "://" in target or target.startswith("#"):
                        continue
                    path = (entry.parent / target.split("#", 1)[0]).resolve()
                    with self.subTest(entry=entry.relative_to(ROOT), target=target):
                        self.assertTrue(path.is_relative_to(boundary), "reference escapes skill distribution")
                        self.assertTrue(path.is_file(), "conditional reference was not shipped")
                        checked += 1
        self.assertGreater(checked, 20)

    def test_documented_harness_commands_use_real_parser(self):
        paths = ("asset-factory/references/authoring.md", "file-organizer/SKILL.md",
                 "excel-to-pipeline/SKILL.md")
        parser = build_parser()
        count = 0
        for relative in paths:
            text = (ROOT / "company-agent-plugin/skills" / relative).read_text(encoding="utf-8")
            for block in re.findall(r"```text\n(.*?)\n[ \t]*```", text, flags=re.S):
                for line in block.splitlines():
                    line = line.strip()
                    if not line.startswith(("asset ", "business ")):
                        continue
                    with self.subTest(source=relative, command=line):
                        args = parser.parse_args(shlex.split(line))
                        self.assertTrue(callable(args.func))
                        count += 1
        self.assertEqual(count, 8)

    def test_minimal_skill_example_creates_and_validates_without_mcp(self):
        text = (ROOT / "company-agent-plugin/skills/asset-factory/references/authoring.md").read_text(encoding="utf-8")
        spec = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "state"
            path = create_asset(spec, state)
            saved = inspect_skill(state, spec["name"])
            command = next(line for line in text.splitlines() if line.startswith("asset validate "))
            # The runtime returns both a directory and an effective SKILL.md file.
            # Run the documented validation command with the actual save result.
            command = command.replace("<생성 결과의 path 폴더>", saved["path"])
            args = build_parser().parse_args(shlex.split(command.replace("\\", "/")))
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = args.func(args)
            self.assertEqual(exit_code, 0)
            result = json.loads(output.getvalue())
            self.assertTrue(result["ok"], result)
            self.assertTrue((path / "SKILL.md").is_file())
            self.assertFalse((path / "server.py").exists())
            self.assertFalse((Path(folder) / ".claude/settings.json").exists())


if __name__ == "__main__":
    unittest.main()
