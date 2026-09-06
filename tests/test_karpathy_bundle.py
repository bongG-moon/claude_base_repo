from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))

from company_agent.frontmatter import parse_frontmatter_text  # noqa: E402


class KarpathyBundleTests(unittest.TestCase):
    skill_root = ROOT / "company-agent-plugin" / "skills" / "karpathy-guidelines"
    source_commit = "2c606141936f1eeef17fa3043a72095b4765b9c2"
    source_sha256 = "6e22cc54cb02a5e98ae42d06d9d7292db0c1b43894831b32879beb0166b2aea7"

    def test_preserved_upstream_matches_the_pinned_source(self) -> None:
        original = self.skill_root / "references" / "UPSTREAM_SKILL.md"
        self.assertEqual(self.source_sha256, hashlib.sha256(original.read_bytes()).hexdigest())
        source = (self.skill_root / "SOURCE.md").read_text(encoding="utf-8")
        self.assertIn(self.source_commit, source)
        self.assertIn(self.source_sha256, source)
        self.assertNotEqual(original.read_bytes(), (self.skill_root / "SKILL.md").read_bytes())

    def test_only_company_adapter_is_discoverable_as_a_skill(self) -> None:
        self.assertEqual([self.skill_root / "SKILL.md"], sorted(self.skill_root.rglob("SKILL.md")))
        metadata, body = parse_frontmatter_text(
            (self.skill_root / "SKILL.md").read_text(encoding="utf-8")
        )
        self.assertEqual("karpathy-guidelines", metadata["name"])
        self.assertEqual("MIT", metadata["license"])
        self.assertTrue(metadata["description"])
        self.assertFalse(metadata.get("disable-model-invocation", False))
        self.assertFalse(set(metadata) & {"model", "hooks", "allowed-tools", "context", "agent"})
        self.assertTrue(body.strip())

    def test_adapter_is_self_contained_and_keeps_license_evidence(self) -> None:
        adapter = (self.skill_root / "SKILL.md").read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", adapter):
            if "://" not in target:
                self.assertTrue((self.skill_root / target).is_file(), target)
        notice = (self.skill_root / "SOURCE_LICENSE").read_text(encoding="utf-8")
        self.assertIn(self.source_commit, notice)
        self.assertIn("no separate full license file or copyright notice", notice)
        self.assertIn("standard MIT reference terms, not a copied upstream notice", notice)
        self.assertIn("Permission is hereby granted", notice)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', notice)
        executables = {".py", ".ps1", ".cmd", ".bat", ".sh", ".exe", ".js"}
        self.assertFalse([path for path in self.skill_root.rglob("*") if path.suffix.lower() in executables])


if __name__ == "__main__":
    unittest.main()
