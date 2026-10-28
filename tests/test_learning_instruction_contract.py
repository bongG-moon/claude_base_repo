"""Executable examples and learning boundaries, independent of guide wording.

These checks exercise the documented CLI/schema against isolated local state.
They do not claim that a live model will follow the instructions.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shlex
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "company-agent-plugin/skills"
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))
from company_agent.cli import build_parser
from company_agent.frontmatter import parse_frontmatter_text
from company_agent.learning import submit_learning
from company_agent.memory import search_memory
from company_agent.state import begin_turn, load_session


class LearningInstructionContractTests(unittest.TestCase):
    entries = ("company-agent", "personal-memory", "personal-knowledge",
               "project-harness", "self-learning", "karpathy-guidelines")

    def text(self, relative):
        return (SKILLS / relative).read_text(encoding="utf-8")

    def sample(self):
        text = self.text("self-learning/references/review-schema.md")
        return json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))

    def test_documented_complete_cli_commands_parse_with_current_runtime(self):
        parser = build_parser()
        examples = []
        for name in self.entries:
            for path in (SKILLS / name).rglob("*.md"):
                # Historical upstream/provenance text is not executable guidance.
                if path.name in {"UPSTREAM_SKILL.md", "SOURCE.md"}:
                    continue
                for command in re.findall(r"`(company-agent [^`\n]+)`", path.read_text(encoding="utf-8")):
                    # Only complete single-command examples are executable examples.
                    if command.endswith("...") or command.startswith("company-agent ..."):
                        continue
                    tokens = shlex.split(command)[1:]
                    for index, value in enumerate(tokens):
                        if value in {"<revision>", "<target>", "<current>"}:
                            tokens[index] = "1"
                        elif value in {"<sha256>", "<current hash>"}:
                            tokens[index] = "a" * 64
                    with self.subTest(path=path, command=command):
                        args = parser.parse_args(tokens)
                        self.assertTrue(callable(args.func))
                    examples.append(command)
        self.assertGreaterEqual(len(examples), 10)

    def test_read_and_write_examples_do_not_change_scope_implicitly(self):
        parser = build_parser()
        read = parser.parse_args(["memory", "search", "보고 형식", "--state-root", "state",
                                  "--project-root", "project", "--limit", "5"])
        self.assertIsNone(read.storage_scope)
        self.assertEqual("보고 형식", read.query)
        for scope in ("personal", "project"):
            update = parser.parse_args(["memory", "upsert", "--spec", "fact.json",
                "--state-root", "state", "--storage-scope", scope, "--project-root", "project",
                "--expected-revision", "2", "--expected-sha256", "a" * 64])
            self.assertEqual(scope, update.storage_scope)
            self.assertEqual(2, update.expected_revision)
            self.assertEqual("a" * 64, update.expected_sha256)

    def test_schema_example_applies_without_checkpoint_or_fake_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            before = begin_turn("docs-learning", "MEDIUM", False, [], state)
            result = submit_learning(state, "docs-learning", before["turnId"], self.sample())
            self.assertEqual(("accepted", 1), (result["status"], result["appliedCount"]))
            after = load_session("docs-learning", state)
            self.assertEqual("active", after["work"]["status"])
            for key in ("verification", "verificationRevision", "stopRetryCount", "mutationCount"):
                self.assertEqual(before.get(key), after.get(key), key)
            saved = search_memory(state, "팀 보고")
            self.assertEqual(1, len(saved))
            duplicate = submit_learning(state, "docs-learning", before["turnId"], self.sample())
            self.assertEqual(("duplicate", 0), (duplicate["status"], duplicate["appliedCount"]))

    def test_missing_procedural_evidence_does_not_become_applied_learning(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            turn = begin_turn("docs-procedure", "MEDIUM", False, [], state)["turnId"]
            spec = self.sample()
            spec["observations"][0].update(kind="skill", skillName="unobserved-skill", signal="verified_fix")
            result = submit_learning(state, "docs-procedure", turn, spec)
            self.assertEqual(0, result["appliedCount"])
            self.assertFalse(list(state.rglob("SKILL.md")))
            self.assertIsNone(load_session("docs-procedure", state).get("verification"))

    def test_learning_schema_rejects_cross_scope_and_raw_transcripts(self):
        for forbidden in ("storageScope", "targetMemoryId", "targetRoot"):
            with self.subTest(field=forbidden), tempfile.TemporaryDirectory() as temp:
                state = Path(temp) / "state"
                turn = begin_turn("docs-private", "SMALL", False, [], state)["turnId"]
                spec = copy.deepcopy(self.sample())
                spec["observations"][0][forbidden] = "unapproved-target"
                with self.assertRaises(ValueError):
                    submit_learning(state, "docs-private", turn, spec)
                self.assertFalse((state / "learning/state.json").exists())
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            turn = begin_turn("docs-private", "SMALL", False, [], state)["turnId"]
            spec = self.sample()
            spec["transcript"] = "source-must-not-be-retained"
            with self.assertRaises(ValueError):
                submit_learning(state, "docs-private", turn, spec)
            self.assertFalse((state / "learning/state.json").exists())

    def test_support_entries_add_no_native_execution_or_automatic_import(self):
        for name in self.entries:
            text = self.text(f"{name}/SKILL.md")
            metadata, _ = parse_frontmatter_text(text)
            with self.subTest(skill=name):
                self.assertEqual(name, metadata["name"])
                self.assertFalse(set(metadata) & {"hooks", "model", "agent", "context", "allowed-tools"})
                self.assertNotRegex(text, r"(?m)^\s*@[^\s]+\.md")
                self.assertLessEqual(len(text), 6500)
        # Support skills stay outside ordinary competing workflow selection.
        for name in ("company-agent", "self-learning", "karpathy-guidelines"):
            metadata, _ = parse_frontmatter_text(self.text(f"{name}/SKILL.md"))
            self.assertEqual("support", metadata["company-agent-role"])

    def test_conditional_references_and_standalone_resources_are_resolvable(self):
        for base in (SKILLS, ROOT / "standalone-skills"):
            for name in self.entries:
                entry = base / name / "SKILL.md"
                if not entry.exists():
                    continue
                text = entry.read_text(encoding="utf-8")
                references = re.findall(r"`(references/[^\s`]+\.md)`", text)
                references += re.findall(r"\]\((references/[^)]+\.md)\)", text)
                for reference in references:
                    with self.subTest(entry=entry, reference=reference):
                        self.assertTrue((entry.parent / reference).is_file())
                        self.assertTrue((entry.parent / reference).resolve().is_relative_to(entry.parent.resolve()))


if __name__ == "__main__":
    unittest.main()
