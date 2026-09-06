from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent.context_audit import audit_context


class ContextAuditTests(unittest.TestCase):
    def test_audit_is_read_only_and_character_budget_catches_long_single_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            config = root / "profile"
            config.mkdir()
            one = project / "CLAUDE.md"
            two = config / "CLAUDE.md"
            one.write_text("NOT-FOR-OUTPUT\n" * 201, encoding="utf-8")
            two.write_text("a" * 12_001, encoding="utf-8")
            before = {path: path.read_bytes() for path in (one, two)}
            result = audit_context(project, config_root=config)
            selected = {item["path"]: item for item in result["files"]}
            self.assertTrue(selected[str(one)]["overBudget"])
            self.assertTrue(selected[str(two)]["overBudget"])
            self.assertNotIn("NOT-FOR-OUTPUT", str(result))
            self.assertEqual(before, {path: path.read_bytes() for path in (one, two)})

    def test_audit_does_not_follow_unconditional_imports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "CLAUDE.md").write_text("@external.md", encoding="utf-8")
            (root / "external.md").write_text("not loaded\n" * 300, encoding="utf-8")
            result = audit_context(root, config_root=root / "profile")
            self.assertNotIn(str(root / "external.md"), str(result))
            self.assertIn("not expanded", result["note"])


if __name__ == "__main__":
    unittest.main()
