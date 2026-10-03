"""Fresh DOTS lifecycle audit through isolated native CLI and hook processes.

This is not a real Claude/model trial. User directions, company knowledge and
host tool events are synthetic. Real persistence, scope selection, hook output,
revision guards and learning decisions run unmocked. A child-process audit guard
rejects Python network access and nested processes (including any model CLI).
Set DOTS_MEMORY_EVIDENCE to a directory to retain command/result/timing evidence.
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
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
sys.path.insert(0, str(PLUGIN / "scripts"))
from company_agent.frontmatter import dump_frontmatter, load_markdown


class DotsMemoryLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dots-memory-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.plugin = self.base / "plugin"
        shutil.copytree(PLUGIN, self.plugin, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "runtime", "company-agent-install.json"))
        self.state = self.base / "state"
        self.config = self.base / "isolated-config"
        self.config.mkdir()
        self.projects = [self.base / name for name in ("project-a", "project-b")]
        for project in self.projects:
            project.mkdir()
            (project / "CLAUDE.md").write_text("# Synthetic audit project\n", encoding="utf-8")
        self.knowledge = self.base / "company-knowledge"
        self.write_json(self.knowledge / "pack.json", {"version": "synthetic-1"})
        self.corporate_file = self.knowledge / "metric-audit.md"
        self.corporate_file.write_text(dump_frontmatter({
            "id": "metric.audit.yield", "kind": "metric", "title": "등대 수율",
            "domain": "synthetic", "owner": "audit-fixture", "status": "active",
        }, "회사 가상 기준: 합격 수를 전체 수로 나눈다. 재작업은 포함한다."), encoding="utf-8")
        self.corporate_original = self.corporate_file.read_bytes()
        registry = self.base / "registrations"
        self.write_json(registry / "user/company-agent-install.json", {
            "schemaVersion": 1, "scope": "User", "enabled": True,
            "userStateRoot": str(self.state), "knowledgeBaseRoot": str(self.knowledge),
            "claudeConfigRoot": str(self.config), "claudeConfigDirOverride": True,
            "projectRoot": None,
        })
        self.write_json(self.plugin / "company-agent-install.json", {
            "registrationsRoot": str(registry), "knowledgeBaseRoot": str(self.knowledge),
            "pythonCommand": sys.executable,
        })
        guard = self.base / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(
            "import json, os, sys\n"
            "with open(os.environ['DOTS_AUDIT_GUARD_LOG'], 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps({'started': os.getpid()}) + '\\n')\n"
            "def deny_external(event, args):\n"
            "    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.posix_spawn'):\n"
            "        with open(os.environ['DOTS_AUDIT_GUARD_LOG'], 'a', encoding='utf-8') as f:\n"
            "            f.write(json.dumps({'blocked': event}) + '\\n')\n"
            "        raise RuntimeError('DOTS audit forbids network and nested processes')\n"
            "sys.addaudithook(deny_external)\n", encoding="utf-8")
        self.guard_log = self.base / "guard.jsonl"
        self.env = {key: value for key, value in os.environ.items() if not key.upper().startswith(
            ("COMPANY_AGENT", "COMPANY_WORKSPACE", "CLAUDE", "ANTHROPIC", "OPENAI", "PYTHON"))}
        self.env.update({"CLAUDE_CONFIG_DIR": str(self.config), "PYTHONUTF8": "1",
                         "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                         "PYTHONPATH": str(guard), "DOTS_AUDIT_GUARD_LOG": str(self.guard_log),
                         "COMPANY_AGENT_PYTHON": sys.executable})
        self.calls = []
        self.addCleanup(self.save_evidence)

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_evidence(self):
        destination = os.environ.get("DOTS_MEMORY_EVIDENCE")
        if destination:
            guard = [json.loads(line) for line in self.guard_log.read_text(encoding="utf-8").splitlines()] if self.guard_log.exists() else []
            result = getattr(getattr(self, "_outcome", None), "result", None)
            failed = any(case.id().startswith(self.id()) for case, _ in
                         [*getattr(result, "failures", []), *getattr(result, "errors", [])])
            sources = ["native_entry.py", "company_agent/memory.py", "company_agent/memory_history.py",
                       "company_agent/resource_scope.py", "company_agent/learning.py", "company_agent/state.py",
                       "company_agent/work.py", "company_agent/native_runtime.py", "company_agent/cli.py"]
            self.write_json(Path(destination) / ("memory-" + self._testMethodName + ".json"), {
                "case": self._testMethodName, "synthetic": True,
                "assertionsPassed": not failed,
                "sourceSha256": {name: hashlib.sha256((self.plugin / "scripts" / name).read_bytes()).hexdigest()
                                 for name in sources},
                "actualModelApplication": "not-observable", "externalModelCalls": "forbidden",
                "entrypoint": "native_entry.py actual subprocess", "calls": self.calls,
                "guard": guard,
                "corporateSourceUnchanged": self.corporate_file.read_bytes() == self.corporate_original,
                "settingsFilesCreated": [str(path.relative_to(self.config)) for path in self.config.rglob("*") if path.is_file()],
            })

    def invoke(self, arguments, *, payload=None, project=None, code=0):
        command = [sys.executable, "-B", str(self.plugin / "scripts/native_entry.py"), *arguments]
        started = time.perf_counter()
        process = subprocess.run(command, cwd=project or self.projects[0], env=self.env,
                                 input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                                 text=True, encoding="utf-8", capture_output=True, timeout=30)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        output = process.stdout.strip() or process.stderr.strip()
        try:
            value = json.loads(output)
        except ValueError:
            value = {"unparsed": output}
        self.calls.append({"command": command, "cwd": str(project or self.projects[0]),
                           "input": payload, "exitCode": process.returncode, "elapsedMs": elapsed,
                           "output": value, "stderr": process.stderr})
        self.assertEqual(code, process.returncode, process.stdout + process.stderr)
        guard = [json.loads(line) for line in self.guard_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(self.calls), sum("started" in entry for entry in guard))
        self.assertFalse([entry for entry in guard if "blocked" in entry], guard)
        self.assertEqual(self.corporate_original, self.corporate_file.read_bytes())
        self.assertFalse(list(self.config.rglob("*.json")), "Isolated Claude settings must remain untouched")
        return value

    def cli(self, *arguments, **options):
        return self.invoke(["--cli", *map(str, arguments)], **options)

    def hook(self, event, sid, *, project=None, **payload):
        project = project or self.projects[0]
        return self.invoke(["--event", event], payload={"session_id": sid, "cwd": str(project), **payload}, project=project)

    def session(self, sid):
        return json.loads((self.state / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))

    def prompt(self, sid, text="등대 보고 순서를 알려줘", *, project=None):
        response = self.hook("UserPromptSubmit", sid, prompt=text, project=project)
        self.assertNotIn("systemMessage", response)
        context = response["hookSpecificOutput"]["additionalContext"]
        route = next(json.loads(line) for line in context.splitlines()
                     if line.startswith("{") and "company_agent_route" in json.loads(line))
        memory = route.get("company_agent_personal_memory_context", "")
        items = (json.loads(memory.split("<company-agent-personal-memory-data>\n", 1)[1]
                            .split("\n</company-agent-personal-memory-data>", 1)[0])["items"] if memory else [])
        return items, self.session(sid), context

    def memory(self, action, *arguments, scope="personal", project=None, code=0):
        return self.cli("memory", action, *arguments, "--storage-scope", scope,
                        "--project-root", project or self.projects[0], project=project, code=code)

    def upsert(self, identifier, body, *, title="등대 보고", kind="preference", scope="personal",
               prior=None, status="active", code=0):
        spec = self.base / "memory-spec.json"
        self.write_json(spec, {"id": identifier, "kind": kind, "title": title, "body": body, "status": status})
        expected = ["--expected-revision", prior["revision"], "--expected-sha256", prior["sha256"]] if prior else []
        return self.memory("upsert", "--spec", spec, *expected, scope=scope, code=code)

    def verify(self, sid, status="pass"):
        return self.cli("session", "verify", "--session", sid, "--status", status,
                        "--summary", "Synthetic fixture assertion checked in this test", code=1 if status == "fail" else 0)

    def observation(self, signal="explicit_correction", **fields):
        return {"kind": "preference", "key": "lighthouse-order", "signal": signal,
                "title": "등대 보고", "body": "등대 보고는 결론 다음 표 순서로 쓴다.", **fields}

    def submit(self, sid, observations=None, outcome="unknown", *, turn=None, code=0):
        turn = turn or self.session(sid)["turnId"]
        spec = self.state / "tmp" / f"learning-review-{turn}.json"
        self.write_json(spec, {"schemaVersion": 1, "taskType": "synthetic-report", "outcome": outcome,
                               "summary": "가상 보고의 재사용 기준", "observations": observations or [], "evaluations": []})
        response = self.cli("learning", "submit", "--session", sid, "--turn", turn, "--spec", spec, code=code)
        self.assertFalse(spec.exists())
        return response

    def learning(self, sid=None):
        arguments = ["--session", sid] if sid else []
        before = {str(path): path.read_bytes() for path in self.state.rglob("*") if path.is_file()}
        value = self.cli("learning", "status", *arguments)["learning"]
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.state.rglob("*") if path.is_file()})
        return value

    def test_manual_scope_revision_deactivate_restore_and_stale_protection(self):
        spec = self.base / "choice.json"
        self.write_json(spec, {"id": "memory.preference.report", "title": "등대 보고", "body": "표 먼저"})
        choice = self.cli("memory", "upsert", "--spec", spec)
        self.assertEqual(("needs_scope_choice", False), (choice["status"], choice["written"]))
        self.assertFalse(list(self.state.glob("**/memory/items/*.md")))
        self.cli("memory", "upsert", "--spec", spec, "--storage-scope", "company", code=2)
        self.assertFalse(list(self.state.glob("**/memory/items/*.md")))
        for scope in ("personal", "project"):
            with self.subTest(scope=scope):
                identifier = "memory.preference.report"
                first = self.upsert(identifier, f"{scope} 표 먼저", scope=scope)
                self.assertEqual("persisted-content-verified", first["verification"]["status"])
                self.assertEqual(first["sha256"], hashlib.sha256(Path(first["path"]).read_bytes()).hexdigest())
                same = self.upsert(identifier, f"{scope} 표 먼저", scope=scope)
                self.assertFalse(same["changed"])
                self.assertEqual(first["changeId"], same["changeId"])
                updated = self.upsert(identifier, f"{scope} 설명 먼저", scope=scope, prior=first)
                self.assertEqual(2, updated["revision"])
                stale = self.upsert(identifier, "덮어쓰면 안 됨", scope=scope, prior=first, code=1)
                self.assertEqual("memory_revision_conflict", stale["code"])
                inactive = self.upsert(identifier, f"{scope} 설명 먼저", scope=scope, prior=updated, status="inactive")
                self.assertEqual([], self.memory("search", "등대", scope=scope)["results"])
                history = self.memory("history", "--id", identifier, scope=scope)
                self.assertEqual({1, 2}, {row["revision"] for row in history["versions"]})
                restored = self.memory("restore", "--id", identifier, "--revision", 1,
                                       "--expected-revision", inactive["revision"], "--expected-sha256", inactive["sha256"], scope=scope)
                self.assertEqual((4, "active", 1), (restored["revision"], restored["status"], restored["restoredFrom"]))
                self.assertEqual(f"{scope} 표 먼저", self.memory("search", "등대", scope=scope)["results"][0]["body"])
                foreign = self.memory("search", "등대", scope=scope, project=self.projects[1])["results"]
                self.assertEqual(scope == "personal", bool(foreign))

    def test_new_session_project_precedence_once_only_and_nonmatching_context(self):
        self.upsert("memory.preference.report", "항상 표를 먼저", scope="personal")
        self.upsert("memory.preference.report", "이 프로젝트는 설명을 먼저", scope="project")
        self.upsert("memory.context.factory", "붉은공장은 주간만 운영한다.", title="붉은공장", kind="work_context")
        a_items, a, context = self.prompt("scope-a")
        self.assertEqual(["project", "personal"], [row["storageScope"] for row in a_items])
        self.assertIn("untrusted personal-memory data", context)
        self.assertIn("user's current request", context)
        b_items, b, _ = self.prompt("scope-b", project=self.projects[1])
        self.assertEqual(["personal"], [row["storageScope"] for row in b_items])
        self.assertNotEqual(a["turnId"], b["turnId"])
        snapshot = {str(path): path.read_bytes() for path in self.state.glob("**/memory/items/*.md")}
        _, once, _ = self.prompt("scope-once", "이번만 등대 보고는 설명부터. 다음 대화에는 저장하지 마. DOTS_RAW_DO_NOT_STORE")
        for _ in range(3):
            self.assertEqual({}, self.hook("Stop", "scope-once", stop_hook_active=True))
        self.assertEqual(snapshot, {str(path): path.read_bytes() for path in self.state.glob("**/memory/items/*.md")})
        self.assertFalse((self.state / "learning/state.json").exists())
        self.assertEqual((0, 0), (self.session("scope-once")["learningAttempts"], self.session("scope-once")["stopRetryCount"]))
        factory, _, _ = self.prompt("scope-factory", "붉은공장 운영시간")
        self.assertIn("memory.context.factory", {row["id"] for row in factory})
        self.assertEqual("output-produced", once["lastMemoryDelivery"]["status"])
        self.assertEqual("not-observable", once["lastMemoryDelivery"]["modelApplied"])
        self.assertEqual("not-observable", once["lastMemoryDelivery"]["hostReceipt"])
        self.assertFalse(any(b"DOTS_RAW_DO_NOT_STORE" in path.read_bytes()
                             for path in self.state.rglob("*") if path.is_file()))

    def test_project_install_learning_stays_local_while_registered_personal_memory_reuses(self):
        personal = self.upsert("memory.preference.shared", "개인 전체 설명 방식", title="공유 가상 설명")
        user_state = self.state
        project_state = self.base / "project-install-state"
        self.write_json(self.base / "registrations/projects/a/company-agent-install.json", {
            "schemaVersion": 1, "scope": "Project", "enabled": True,
            "projectRoot": str(self.projects[0]), "userStateRoot": str(project_state),
            "knowledgeBaseRoot": str(self.knowledge), "claudeConfigRoot": str(self.config),
            "claudeConfigDirOverride": True,
        })
        self.state = project_state
        items, _, _ = self.prompt("project-learn")
        self.assertIn((personal["id"], "personal"), {(row["id"], row["storageScope"]) for row in items})
        learned = self.submit("project-learn", [self.observation()])
        self.assertEqual("project", learned["storage"]["storageScope"])
        change = learned["changes"][0]
        self.assertTrue((project_state / "memory/items" / (change["memoryId"] + ".md")).exists())
        items, _, _ = self.prompt("project-new-session")
        self.assertIn((change["memoryId"], "project"), {(row["id"], row["storageScope"]) for row in items})
        self.state = user_state
        items, _, _ = self.prompt("unrelated-project", project=self.projects[1])
        self.assertIn(personal["id"], {row["id"] for row in items})
        self.assertNotIn(change["memoryId"], {row["id"] for row in items})
        self.assertFalse((user_state / "learning/state.json").exists())

    def test_existing_human_preference_defers_automatic_overlap_without_replacing_it(self):
        manual = self.upsert("memory.preference.manual-order", "사람이 정한 설명 다음 표 순서")
        original = Path(manual["path"]).read_bytes()
        self.prompt("human-conflict")
        result = self.submit("human-conflict", [self.observation()])
        self.assertEqual((0, 1), (result["appliedCount"], result["deferredCount"]))
        self.assertIn("existing human preference", result["changes"][0]["reason"])
        self.assertEqual(original, Path(manual["path"]).read_bytes())
        self.assertEqual({}, self.hook("Stop", "human-conflict", stop_hook_active=True))
        self.assertEqual(0, self.session("human-conflict")["learningAttempts"])

    def test_skill_changed_after_observed_read_is_deferred_until_exact_revision_read(self):
        sid = "skill-stale"
        path = self.state / "personal-root/.claude/skills/audit-report/SKILL.md"
        path.parent.mkdir(parents=True)
        original = "---\nname: audit-report\ndescription: Synthetic report\n---\nCheck counts.\n"
        path.write_text(original, encoding="utf-8")
        self.prompt(sid)
        self.hook("PostToolUse", sid, tool_name="Read", tool_input={"file_path": str(path)},
                  tool_response={"file": {"content": original, "startLine": 1}})
        changed = original + "User added a manual check.\n"
        path.write_text(changed, encoding="utf-8")
        self.verify(sid)
        lesson = self.observation(kind="skill", key="confirm-count", skillName="audit-report",
                                  title="가상 수량 확인", body="제출 전에 입력 수량과 출력 수량을 대조한다.")
        deferred = self.submit(sid, [lesson], outcome="success")
        self.assertEqual(1, deferred["deferredCount"])
        self.assertIn("unchanged personal revision", deferred["changes"][0]["reason"])
        self.assertEqual(changed, path.read_text(encoding="utf-8"))
        self.prompt(sid)
        self.hook("PostToolUse", sid, tool_name="Read", tool_input={"file_path": str(path)},
                  tool_response={"file": {"content": changed, "startLine": 1}})
        self.verify(sid)
        accepted = self.submit(sid, outcome="success")
        self.assertEqual(1, accepted["appliedCount"])
        self.assertTrue(path.read_text(encoding="utf-8").startswith(changed))

    def test_company_rule_project_fork_preserves_origin_and_other_project(self):
        self.cli("knowledge", "build")
        spec = self.base / "fork.json"
        self.write_json(spec, {"id": "personal.fork.audit-yield", "title": "등대 프로젝트 수율",
                               "mode": "fork", "extends": "metric.audit.yield",
                               "body": "가상 A 프로젝트 기준: 재작업을 제외한 수를 분모로 쓴다."})
        result = self.cli("knowledge", "upsert", "--spec", spec, "--storage-scope", "project", "--project-root", self.projects[0])
        self.assertTrue(Path(result["path"]).is_relative_to(self.state / "project-scopes"))
        a = self.cli("knowledge", "search", "등대", "--project-root", self.projects[0])["results"]
        b = self.cli("knowledge", "search", "등대", "--project-root", self.projects[1], project=self.projects[1])["results"]
        self.assertEqual("project", a[0]["storageScope"])
        self.assertEqual("corporate", a[0]["source"])
        self.assertEqual("fork", a[0]["overlays"][0]["mode"])
        self.assertEqual(str(self.corporate_file), a[0]["path"])
        self.assertTrue(all(not row["overlays"] for row in b))
        self.assertEqual(self.corporate_original, self.corporate_file.read_bytes())

    def test_learning_explicit_once_delivery_pause_resume_targeted_rollback(self):
        self.prompt("learn-explicit")
        before = self.session("learn-explicit")
        first = self.submit("learn-explicit", [self.observation()])
        self.assertEqual(("accepted", "captured", 1, 1, 0), tuple(first[key] for key in
                         ("status", "captureStatus", "capturedCount", "appliedCount", "deferredCount")))
        self.assertEqual("personal", first["storage"]["storageScope"])
        after = self.session("learn-explicit")
        for key in ("mutationCount", "verification", "stopRetryCount"):
            self.assertEqual(before[key], after[key])
        self.assertEqual("active", after["work"]["status"])
        change = first["changes"][0]
        repeated = self.submit("learn-explicit", [self.observation(key="different-key")])
        self.assertEqual(("duplicate", 0, 0), (repeated["status"], repeated["capturedCount"], repeated["appliedCount"]))
        items, delivered, _ = self.prompt("learn-new-session", project=self.projects[1])
        self.assertIn(change["memoryId"], {row["id"] for row in items})
        self.assertEqual("output-produced", delivered["lastMemoryDelivery"]["status"])
        status = self.learning("learn-new-session")
        self.assertEqual("not_submitted", status["currentSubmission"]["captureStatus"])
        self.assertEqual(1, status["activeChanges"])
        self.assertFalse(self.cli("learning", "pause")["enabled"])
        paused = self.submit("learn-new-session", [self.observation(key="paused-key")])
        self.assertEqual("disabled", paused["status"])
        self.assertTrue(self.cli("learning", "resume")["enabled"])
        undo = self.cli("learning", "rollback", "--change", change["id"])
        self.assertEqual(("rolled_back", "deactivate_preference", False),
                         (undo["status"], undo["operation"], undo["previousContentRestored"]))
        items, state, _ = self.prompt("learn-after-rollback")
        self.assertNotIn(change["memoryId"], {row["id"] for row in items})
        self.assertEqual("inactive", load_markdown(self.state / "memory/items" / (change["memoryId"] + ".md")).metadata["status"])
        for _ in range(3):
            self.assertEqual({}, self.hook("Stop", "learn-after-rollback", stop_hook_active=True))
        self.assertEqual(0, self.session("learn-after-rollback")["learningAttempts"])

    def test_repeated_choice_needs_independent_verified_work_not_extra_turns(self):
        sid = "learn-repeated"
        observation = self.observation("repeated_choice")
        self.prompt(sid)
        deferred = self.submit(sid, [observation])
        self.assertEqual((0, 1), (deferred["appliedCount"], deferred["deferredCount"]))
        self.assertEqual({}, self.hook("Stop", sid, stop_hook_active=True))
        first_work = self.session(sid)["work"]["id"]
        for _ in range(2):
            self.prompt(sid)
            self.verify(sid)
            observing = self.submit(sid, [observation], outcome="success")
            self.assertEqual(0, observing["appliedCount"])
            self.assertEqual(first_work, self.session(sid)["work"]["id"])
            current = self.learning(sid)
            self.assertEqual((0, 1), (current["activeChanges"], current["recentCandidates"][0]["userChoiceTurns"]))
        self.prompt(sid)
        self.cli("work", "checkpoint", "--session", sid, "--turn", self.session(sid)["turnId"], "--status", "active", "--new", "yes")
        self.verify(sid)
        applied = self.submit(sid, [observation], outcome="success")
        self.assertEqual(1, applied["appliedCount"])
        self.assertNotEqual(first_work, self.session(sid)["work"]["id"])
        self.assertEqual(2, self.learning(sid)["recentCandidates"][0]["userChoiceTurns"])

    def test_skill_lesson_requires_exact_read_failure_then_verified_success(self):
        sid = "learn-skill"
        path = self.state / "personal-root/.claude/skills/audit-report/SKILL.md"
        path.parent.mkdir(parents=True)
        original = "---\nname: audit-report\ndescription: Synthetic audit report\n---\n# Report\nCheck the count.\n"
        path.write_text(original, encoding="utf-8")
        lesson = self.observation("verified_fix", kind="skill", key="check-denominator", skillName="audit-report",
                                  title="분모 확인", body="수율을 계산하기 전에 전체 수와 제외 수를 각각 확인한다.")
        self.prompt(sid)
        self.verify(sid)
        missing = self.submit(sid, [lesson], outcome="success")
        self.assertEqual(1, missing["deferredCount"])
        self.assertEqual(original, path.read_text(encoding="utf-8"))
        self.prompt(sid)
        self.hook("PostToolUse", sid, tool_name="Read", tool_input={"file_path": str(path)},
                  tool_response={"file": {"content": original, "startLine": 1}})
        observed = self.session(sid)["usedSkills"]
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), observed[0]["sha256"])
        self.verify(sid)
        no_failure = self.submit(sid, outcome="success")
        self.assertEqual(1, no_failure["deferredCount"])
        self.assertEqual(original, path.read_text(encoding="utf-8"))
        self.prompt(sid)
        self.verify(sid, "fail")
        self.verify(sid)
        applied = self.submit(sid, outcome="success")
        self.assertEqual(1, applied["appliedCount"])
        self.assertIn("company-agent-learning:begin", path.read_text(encoding="utf-8"))
        self.assertTrue(path.read_text(encoding="utf-8").startswith(original))
        self.assertGreater(applied["evidence"]["verificationFailures"], 0)
        self.assertEqual({}, self.hook("Stop", sid, stop_hook_active=True))
        self.cli("learning", "rollback", "--change", applied["changes"][0]["id"])
        self.assertEqual(original, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
