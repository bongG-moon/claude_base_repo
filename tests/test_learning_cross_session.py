"""Isolated process integration, not evidence of an LLM applying a memory.

The PowerShell launcher/native hook and CLI really execute. Hook payloads,
corrections and registration records are synthetic; no Claude account, model,
network, existing personal state or business document is used. This connects
submit -> distinct-session delivery -> targeted rollback -> future exclusion.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
sys.path.insert(0, str(PLUGIN / "scripts"))
from company_agent.frontmatter import load_markdown
from company_agent.memory import MEMORY_CONTEXT_BEGIN, MEMORY_CONTEXT_END
from company_agent.paths import atomic_write_json, atomic_write_text


class LearningCrossSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="learning-cross-session-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.plugin = self.base / "plugin copy"
        shutil.copytree(PLUGIN, self.plugin, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "runtime", "company-agent-install.json"))
        self.state = self.base / "개인 학습 상태"
        self.config = self.base / "isolated-claude"
        self.knowledge = self.base / "knowledge"
        self.projects = [self.base / name for name in ("project-a", "project-b")]
        self.config.mkdir()
        for project in self.projects:
            project.mkdir()
            atomic_write_text(project / "CLAUDE.md", "# Synthetic learning test\n")
        atomic_write_json(self.knowledge / "pack.json", {"version": "fixture"})
        registry = self.base / "registrations"
        atomic_write_json(registry / "user/company-agent-install.json", {
            "schemaVersion": 1, "scope": "User", "enabled": True,
            "userStateRoot": str(self.state), "knowledgeBaseRoot": str(self.knowledge),
            "claudeConfigRoot": str(self.config), "claudeConfigDirOverride": True,
            "projectRoot": None,
        })
        atomic_write_json(self.plugin / "company-agent-install.json", {
            "registrationsRoot": str(registry), "knowledgeBaseRoot": str(self.knowledge),
            "pythonCommand": sys.executable,
        })
        # Do not inherit active runtime/profile/worker flags or model credentials.
        self.env = {key: value for key, value in os.environ.items() if not key.upper().startswith(
            ("COMPANY_AGENT", "COMPANY_WORKSPACE", "CLAUDE", "ANTHROPIC", "OPENAI"))}
        self.env.update({"CLAUDE_CONFIG_DIR": str(self.config), "PYTHONUTF8": "1",
                         "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                         "COMPANY_AGENT_PYTHON": sys.executable})

    def invoke(self, *arguments, payload=None, project=None):
        """Actual launcher/native entry subprocess; no functions are mocked."""
        powershell = shutil.which("powershell.exe") if os.name == "nt" else None
        if powershell:
            command = [powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                       str(self.plugin / "scripts/Invoke-CompanyAgent.ps1"), *arguments]
        else:
            native_args = (["--cli", *arguments[2:]] if arguments[:2] == ("-Mode", "Cli")
                           else ["--event", arguments[3]])
            command = [sys.executable, "-B", str(self.plugin / "scripts/native_entry.py"), *native_args]
        result = subprocess.run(command, cwd=project or self.projects[0], env=self.env,
                                input=json.dumps(payload, ensure_ascii=False) if payload else None,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def cli(self, *arguments, project=None):
        return self.invoke("-Mode", "Cli", *arguments, project=project)

    def session(self, sid):
        return json.loads((self.state / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))

    def prompt(self, sid, query="노랑등대 검증보고 형식은?", project=None):
        project = project or self.projects[0]
        response = self.invoke("-Mode", "Hook", "-Event", "UserPromptSubmit", project=project,
                               payload={"session_id": sid, "prompt": query, "cwd": str(project)})
        context = response["hookSpecificOutput"]["additionalContext"]
        route = next(json.loads(line) for line in context.split("\n")
                     if line.startswith("{") and "company_agent_route" in json.loads(line))
        memory = route.get("company_agent_personal_memory_context", "")
        items = []
        if memory:
            items = json.loads(memory.split(MEMORY_CONTEXT_BEGIN + "\n", 1)[1]
                               .split("\n" + MEMORY_CONTEXT_END, 1)[0])["items"]
        return items, self.session(sid)

    def submit(self, sid, *, key="yellow-lighthouse-order", title="노랑등대 검증보고",
               body="노랑등대 검증보고는 결론, 수치 표, 다음 행동 순서로 쓴다."):
        turn = self.session(sid)["turnId"]
        spec = self.state / "tmp" / f"learning-review-{turn}.json"
        atomic_write_json(spec, {"schemaVersion": 1, "taskType": "synthetic-report", "outcome": "unknown",
                                "summary": "가상 보고의 지속적인 순서 교정",
                                "observations": [{"kind": "preference", "key": key,
                                    "signal": "explicit_correction", "title": title, "body": body}],
                                "evaluations": []})
        result = self.cli("learning", "submit", "--session", sid, "--turn", turn, "--spec", str(spec))
        self.assertEqual("removed", result["stagingCleanup"])
        self.assertFalse(spec.exists())
        return result

    def manual(self, identifier, title, body, scope="personal", project=None):
        spec = self.base / (identifier + ".json")
        atomic_write_json(spec, {"id": identifier, "kind": "preference", "title": title, "body": body})
        return self.cli("memory", "upsert", "--spec", str(spec), "--storage-scope", scope,
                        "--project-root", str(project or self.projects[0]), project=project)

    def test_submit_new_session_delivery_rollback_and_future_exclusion_preserve_manual_scopes(self):
        personal = self.manual("memory.preference.manual-contact", "가상연락 기준", "가상연락은 메일로 한다.")
        project = self.manual("memory.preference.manual-annotation", "노랑등대 주석", "A에서만 주석을 표시한다.", "project")
        preserved = {Path(item["path"]): Path(item["path"]).read_bytes() for item in (personal, project)}
        self.prompt("learn-first")
        learned = self.submit("learn-first")
        self.assertEqual(("accepted", 1, 0), (learned["status"], learned["appliedCount"], learned["deferredCount"]))
        self.assertEqual("personal", learned["storage"]["storageScope"])
        change, = learned["changes"]
        memory_file = self.state / "memory/items" / (change["memoryId"] + ".md")
        document = load_markdown(memory_file)
        digest = hashlib.sha256(memory_file.read_bytes()).hexdigest()
        self.assertEqual("active", document.metadata["status"])
        self.assertEqual(change["recordedAfterSha256"], digest)
        first = self.session("learn-first")
        self.assertEqual("active", first["work"]["status"])
        self.assertIsNone(first["verification"])

        items, second = self.prompt("learn-distinct-session")
        expected = {"id": change["memoryId"], "revision": document.metadata["revision"], "storageScope": "personal"}
        item = next(item for item in items if item["id"] == change["memoryId"])
        self.assertEqual(expected, {key: item[key] for key in expected})
        self.assertEqual(document.body.strip(), item["body"])
        receipt = second["lastMemoryDelivery"]
        self.assertEqual("output-produced", receipt["status"])
        self.assertIn(expected, receipt["items"])
        self.assertEqual("not-observable", receipt["hostReceipt"])
        self.assertEqual("not-observable", receipt["modelApplied"])
        self.assertNotEqual(first["turnId"], second["turnId"])
        self.assertIn(project["id"], {item["id"] for item in items})
        other_items, _ = self.prompt("other-project", project=self.projects[1])
        self.assertIn(change["memoryId"], {item["id"] for item in other_items})
        self.assertNotIn(project["id"], {item["id"] for item in other_items})

        undone = self.cli("learning", "rollback", "--change", change["id"])
        self.assertEqual(("rolled_back", "deactivate_preference", "preference_deactivated", True),
                         tuple(undone[key] for key in ("status", "operation", "effect", "changed")))
        self.assertFalse(undone["previousContentRestored"])
        inactive = load_markdown(memory_file)
        self.assertEqual("inactive", inactive.metadata["status"])
        self.assertEqual(document.body, inactive.body)
        after_items, after = self.prompt("after-targeted-rollback")
        self.assertNotIn(change["memoryId"], {item["id"] for item in after_items})
        self.assertNotIn(change["memoryId"], {item["id"] for item in after["lastMemoryDelivery"]["items"]})
        self.assertIn(project["id"], {item["id"] for item in after_items})
        for path, original in preserved.items():
            self.assertEqual(original, path.read_bytes())
        self.assertFalse(list(self.config.rglob("*.json")))

    def test_conflict_is_deferred_pause_blocks_capture_and_resume_does_not_replace_manual_memory(self):
        manual = self.manual("memory.preference.manual-order", "노랑등대 검증보고", "사용자가 정한 가상 보고 순서.")
        path = Path(manual["path"])
        original = path.read_bytes()
        self.prompt("conflicting-session")
        conflict = self.submit("conflicting-session")
        self.assertEqual((0, 1), (conflict["appliedCount"], conflict["deferredCount"]))
        self.assertIn("human preference", conflict["changes"][0]["reason"])
        self.assertEqual(original, path.read_bytes())

        self.assertFalse(self.cli("learning", "pause")["enabled"])
        self.prompt("paused-session", query="새벽등대 시험 형식은?")
        paused = self.submit("paused-session", key="dawn-lighthouse", title="새벽등대 시험", body="새벽등대 시험은 표를 먼저 쓴다.")
        self.assertEqual(("disabled", "learning_paused", 0), (paused["status"], paused["reason"], paused["appliedCount"]))
        self.assertEqual([], list((self.state / "memory/items").glob("learning.*.md")))
        manual_items, _ = self.prompt("paused-retrieval")
        self.assertIn(manual["id"], {item["id"] for item in manual_items})

        self.assertTrue(self.cli("learning", "resume")["enabled"])
        self.prompt("resumed-session", query="새벽등대 시험 형식은?")
        resumed = self.submit("resumed-session", key="dawn-lighthouse", title="새벽등대 시험", body="새벽등대 시험은 표를 먼저 쓴다.")
        self.assertEqual(1, resumed["appliedCount"])
        resumed_items, _ = self.prompt("resumed-next-session", query="새벽등대 시험 형식은?")
        self.assertIn(resumed["changes"][0]["memoryId"], {item["id"] for item in resumed_items})
        self.assertEqual(original, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
