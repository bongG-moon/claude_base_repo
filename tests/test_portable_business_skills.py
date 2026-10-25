"""개별 ZIP의 원본을 하네스가 없는 임시 폴더에서 실행하는 회귀 시험."""
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(path):
    spec = importlib.util.spec_from_file_location("portable_" + path.stem, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


class PortableBusinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def copy_skill(self, name):
        target = self.work / name
        shutil.copytree(ROOT / "standalone-skills" / name, target)
        return target

    def run_script(self, script, *args, ok=True):
        env = {k: v for k, v in os.environ.items() if "COMPANY" not in k.upper() and k != "PYTHONPATH"}
        result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", str(script), *map(str, args)],
                                cwd=self.work, env=env, text=True, encoding="utf-8", capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_native_skill_create_isolated_and_existing_source_preserved(self):
        skill = self.copy_skill("asset-factory")
        body = self.work / "body.md"; body.write_text("# 주간 조회\n실제 도구로 필요한 값만 조회합니다.", encoding="utf-8")
        destination = self.work / "weekly-summary"
        args = ("--destination", destination, "--name", "weekly-summary", "--description", "주간 조회", "--body", body)
        result = self.run_script(skill / "scripts/author_skill.py", *args)
        self.assertEqual(Path(result["path"]), destination / "SKILL.md")
        original = (destination / "SKILL.md").read_bytes()
        self.run_script(skill / "scripts/author_skill.py", *args, ok=False)
        self.assertEqual((destination / "SKILL.md").read_bytes(), original)
        self.assertFalse((self.work / ".claude/settings.json").exists())

    def test_skill_bad_name_does_not_create(self):
        skill = self.copy_skill("asset-factory")
        body = self.work / "body.md"; body.write_text("업무", encoding="utf-8")
        self.run_script(skill / "scripts/author_skill.py", "--destination", self.work / "bad", "--name", "../bad", "--description", "설명", "--body", body, ok=False)
        self.assertFalse((self.work / "bad").exists())

    def test_standard_mcp_starter_is_self_contained_and_not_registered(self):
        skill = self.copy_skill("asset-factory")
        destination = self.work / "my-tools"
        result = self.run_script(skill / "scripts/create_project.py", "--destination", destination)
        self.assertFalse(result["registered"])
        self.assertFalse(result["platformVerified"])
        self.assertIn("def register_tools", (destination / "src/mcp/tools.py").read_text(encoding="utf-8"))
        self.assertTrue((destination / "local_server.py").is_file())
        self.assertTrue((destination / "test_tools.py").is_file())
        self.assertFalse((self.work / ".mcp.json").exists())
        self.run_script(skill / "scripts/create_project.py", "--destination", destination, ok=False)

    def test_standard_mcp_template_source_hashes_and_local_copies_match(self):
        skill = ROOT / "standalone-skills/asset-factory"
        sources = json.loads((skill / "assets/template-source.json").read_text(encoding="utf-8-sig"))
        for row in sources:
            source = ROOT / row["path"]
            relative = row["path"].split("assets/template/", 1)[1]
            copied = skill / "assets/template" / relative
            self.assertEqual(row["normalization"], "utf8-lf")
            # Git/Windows 줄바꿈 차이만 정규화한다. 공백과 코드 내용은 그대로 검사한다.
            original = source.read_text(encoding="utf-8").encode("utf-8")
            bundled = copied.read_text(encoding="utf-8").encode("utf-8")
            self.assertEqual(hashlib.sha256(original).hexdigest(), row["sha256"], row["path"])
            self.assertEqual(bundled, original, relative)

    def test_organize_real_move_and_undo_isolated(self):
        skill = self.copy_skill("file-organizer")
        script = skill / "scripts/organize.py"
        files = self.work / "자료"; files.mkdir()
        (files / "보고서.txt").write_text("원본", encoding="utf-8")
        (files / "수치.csv").write_text("열\n1", encoding="utf-8")
        (files / "실행.exe").write_bytes(b"keep")
        (files / "기존폴더").mkdir()
        plan, receipt, undo = (self.work / n for n in ("plan.json", "receipt.json", "undo.json"))
        planned = self.run_script(script, "plan", "--folder", files, "--output", plan)
        self.assertEqual(len(planned["moves"]), 2)
        self.assertTrue((files / "보고서.txt").exists())
        result = self.run_script(script, "apply", "--plan", plan, "--receipt", receipt)
        self.assertEqual(len(result["moves"]), 2)
        self.assertEqual((files / "문서/보고서.txt").read_text(encoding="utf-8"), "원본")
        self.assertFalse((files / "보고서.txt").exists())
        self.run_script(script, "undo", "--receipt", receipt, "--output", undo)
        self.assertEqual((files / "보고서.txt").read_text(encoding="utf-8"), "원본")
        self.assertEqual((files / "실행.exe").read_bytes(), b"keep")

    def test_organize_changed_file_does_not_move(self):
        skill = self.copy_skill("file-organizer"); mod = module(skill / "scripts/organize.py")
        folder = self.work / "files"; folder.mkdir(); source = folder / "a.txt"; source.write_text("before")
        plan = mod.plan(folder); source.write_text("after")
        result = mod.execute(plan, self.work / "receipt.json")
        self.assertTrue(result["failures"]); self.assertTrue(source.exists()); self.assertFalse((folder / "문서/a.txt").exists())

    def test_organize_destination_race_and_path_traversal(self):
        skill = self.copy_skill("file-organizer"); mod = module(skill / "scripts/organize.py")
        folder = self.work / "files"; folder.mkdir(); source = folder / "a.txt"; source.write_text("original")
        plan = mod.plan(folder); (folder / "문서").mkdir(); (folder / "문서/a.txt").write_text("existing")
        result = mod.execute(plan, self.work / "receipt.json")
        self.assertTrue(result["failures"])
        self.assertEqual((folder / "문서/a.txt").read_text(), "existing")
        self.assertEqual(source.read_text(), "original")
        plan["moves"][0]["name"] = "../a.txt"
        with self.assertRaises(ValueError): mod.execute(plan, self.work / "bad.json")
        self.assertFalse((self.work / "bad.json").exists())

    def test_organize_undo_preserves_new_original_and_changed_moved_file(self):
        skill = self.copy_skill("file-organizer"); mod = module(skill / "scripts/organize.py")
        folder = self.work / "files"; folder.mkdir(); source = folder / "a.txt"; source.write_text("original")
        receipt = mod.execute(mod.plan(folder), self.work / "receipt.json")
        source.write_text("new file at original path")
        result = mod.execute(receipt, self.work / "undo-conflict.json", undo=True)
        self.assertTrue(result["failures"])
        self.assertEqual(source.read_text(), "new file at original path")
        self.assertEqual((folder / "문서/a.txt").read_text(), "original")
        source.unlink()
        (folder / "문서/a.txt").write_text("edited moved file")
        result = mod.execute(receipt, self.work / "undo-changed.json", undo=True)
        self.assertTrue(result["failures"]); self.assertFalse(source.exists())
        self.assertEqual((folder / "문서/a.txt").read_text(), "edited moved file")

    def test_eml_metadata_then_bounded_body_without_connector(self):
        skill = self.copy_skill("outlook-assistant"); script = skill / "scripts/mail_read.py"
        msg = EmailMessage(); msg["Subject"] = "실습 신청"; msg["From"] = "sample@example.invalid"
        msg.set_content("가나다라마바사" * 100)
        msg.add_attachment(b"not read", maintype="application", subtype="octet-stream", filename="sample.bin")
        eml = self.work / "sample.eml"; eml.write_bytes(msg.as_bytes())
        result = self.run_script(script, "eml", "--file", eml)
        self.assertEqual(result["bodyReadCount"], 0); self.assertNotIn("body", result)
        self.assertEqual(result["attachments"], ["sample.bin"])
        result = self.run_script(script, "eml", "--file", eml, "--body", "--body-chars", "24")
        self.assertEqual(len(result["body"]), 24); self.assertTrue(result["truncated"])

    def test_outlook_search_never_reads_body_and_read_budget_stops_access(self):
        skill = self.copy_skill("outlook-assistant"); mod = module(skill / "scripts/mail_read.py")
        reads = []
        class Mail:
            Class = 43; Subject = "교육 신청"; SenderName = "가상 발신자"
            ReceivedTime = datetime(2026, 10, 1, tzinfo=timezone.utc)
            Attachments = SimpleNamespace(Count=0)
            def __init__(self, name): self.EntryID = name
            @property
            def Body(self): reads.append(self.EntryID); return "본문" * 100
        mails = {str(i): Mail(str(i)) for i in range(10)}
        class Items:
            Count = 10
            def Sort(self, *args): pass
            def Item(self, index): return mails[str(index - 1)]
        namespace = SimpleNamespace(GetFolderFromID=lambda *args: SimpleNamespace(Items=Items()), GetItemFromID=lambda key, store: mails[key])
        result = mod.search(namespace, "s", "f", "교육", limit=2)
        self.assertEqual(len(result["messages"]), 2); self.assertEqual(reads, []); self.assertTrue(result["partial"])
        result = mod.read(namespace, "s", ["0", "1", "2"], body_chars=20, total_chars=25)
        self.assertEqual(reads, ["0", "1"]); self.assertEqual(result["bodyCharacters"], 25); self.assertEqual(result["omitted"], 1)
        with self.assertRaises(ValueError): mod.search(namespace, "s", "f", after="2026-10-01")

    def test_mail_total_json_budget_keeps_identifiers_whole(self):
        skill = self.copy_skill("outlook-assistant"); mod = module(skill / "scripts/mail_read.py")
        ids = [str(i) + "x" * 4096 for i in range(20)]
        result = mod.bounded_result({"messages": [{"id": i, "subject": "가" * 500, "body": "\\\n" * 500} for i in ids],
                                     "bodyReadCount": 20, "bodyCharacters": 20000, "omitted": 0})
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 32000)
        self.assertTrue(result["outputTruncated"])
        self.assertGreater(result["omitted"], 0)
        self.assertEqual(result["bodyReadCount"], 20)
        self.assertEqual(result["bodyCharacters"], sum(len(row["body"]) for row in result["messages"]))
        self.assertTrue(all(row["id"] in ids for row in result["messages"]))

    def test_portable_entries_do_not_call_company_runtime(self):
        for name in ("asset-factory", "file-organizer", "outlook-assistant"):
            for path in (ROOT / "standalone-skills" / name).rglob("*"):
                if path.suffix not in (".py", ".md"): continue
                text = path.read_text(encoding="utf-8-sig")
                for token in ("company_agent_runtime", "import company_agent", "--state-root", "company-agent:medium-worker"):
                    self.assertNotIn(token, text, str(path))


if __name__ == "__main__":
    unittest.main()
