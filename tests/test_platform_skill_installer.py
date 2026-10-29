"""Isolated installer checks. No live Claude profile or project is modified."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "pt_ai_square/static/guides/pt-file-distribution/scripts/install_scope.py"
if not HELPER.is_file():
    raise unittest.SkipTest("Prepare the current platform distribution skill first")
spec = importlib.util.spec_from_file_location("install_scope", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
sys.modules["install_scope"] = helper
spec = importlib.util.spec_from_file_location("square_test_installer", ROOT / "scripts/platform_skills/install_skill.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".smoke/platform-skills").mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="square-installer-test-", dir=ROOT / ".smoke/platform-skills")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        self.project = self.root / "project"
        self.home = self.root / "synthetic-home"
        self.package.mkdir()
        self.project.mkdir()
        self.home.mkdir()
        self.files = {
            "SKILL.md": b"---\nname: test\ndescription: synthetic\n---\n# Test\n",
            "ai-square.json": json.dumps({"schemaVersion": 1, "packageId": "test"}).encode(),
            "INSTALL.md": b"Test only.\n",
            "references/info.md": b"Synthetic test documentation.\n",
        }
        self.write_package()
        (self.package / "not-in-package.txt").write_text("must not copy", encoding="utf-8")
        self.stdout = io.StringIO()
        self.addCleanup(patch.stopall)
        patch.object(Path, "home", return_value=self.home).start()

    def write_package(self):
        for name, data in self.files.items():
            target = self.package / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.manifest = {"files": {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()}}
        self.write_manifest()

    def write_manifest(self):
        (self.package / "PACKAGE_CONTENTS.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def run_install(self, **kw):
        options = {"scope": "project", "project_dir": str(self.project), "yes": True, "interactive": False, "environ": {}}
        options.update(kw)
        with contextlib.redirect_stdout(self.stdout):
            return installer.install(self.package, **options)

    def related_install(self, *, base=None, name="square-company-test", metadata=None):
        target = (base or self.project) / ".claude/skills" / name
        target.mkdir(parents=True)
        (target / "keep.md").write_text("user changes", encoding="utf-8")
        if metadata is not None:
            (target / "ai-square.json").write_text(metadata, encoding="utf-8")
        return target

    def test_legacy_name_remains_installable(self):
        self.files["ai-square.json"] = json.dumps({"schemaVersion": 1, "packageId": "company.skills.test"}).encode()
        self.files["SKILL.md"] = self.files["SKILL.md"].replace(b"name: test", b"name: square-company-test")
        self.write_package()
        result = self.run_install()
        self.assertEqual(Path(result["target"]), self.project / ".claude/skills/square-company-test")

    def test_same_package_legacy_name_blocks_install_and_dry_run_without_changes(self):
        legacy = self.related_install(metadata=json.dumps({"packageId": "company.skills.test"}))
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), self.assertRaisesRegex(installer.InstallError, "같은 스킬.*다른 이름"):
                self.run_install(dry_run=dry_run)
        self.assertEqual(before, {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertFalse((legacy.parent / "test").exists())
        self.assertFalse(list(legacy.parent.glob(".square-install-*")))

    def test_unknown_legacy_metadata_does_not_allow_silent_duplicate(self):
        legacy = self.related_install()
        for data in (None, "not json", "{}", '{"packageId":""}', " " * 65_537):
            with self.subTest(data=None if data is None else data[:20]):
                if data is not None:
                    (legacy / "ai-square.json").write_text(data, encoding="utf-8")
                with self.assertRaisesRegex(installer.InstallError, "설치 정보를 확인할 수 없습니다"):
                    self.run_install(dry_run=True)
                self.assertEqual((legacy / "keep.md").read_text(encoding="utf-8"), "user changes")
                self.assertFalse((legacy.parent / "test").exists())

    def test_unrelated_package_at_legacy_name_is_preserved(self):
        legacy = self.related_install(metadata=json.dumps({"packageId": "independent.other"}))
        result = self.run_install()
        self.assertEqual(result["status"], "installed")
        self.assertEqual((legacy / "keep.md").read_text(encoding="utf-8"), "user changes")

    def test_legacy_install_in_unselected_scope_is_not_scanned(self):
        legacy = self.related_install(base=self.home, metadata=json.dumps({"packageId": "company.skills.test"}))
        result = self.run_install()
        self.assertEqual(result["status"], "installed")
        self.assertEqual((legacy / "keep.md").read_text(encoding="utf-8"), "user changes")

    def test_new_name_blocks_legacy_same_package_install(self):
        self.files["ai-square.json"] = json.dumps({"schemaVersion": 1, "packageId": "company.skills.test"}).encode()
        self.files["SKILL.md"] = self.files["SKILL.md"].replace(b"name: test", b"name: square-company-test")
        self.write_package()
        current = self.related_install(name="test", metadata=json.dumps({"packageId": "test"}))
        with self.assertRaisesRegex(installer.InstallError, "같은 스킬.*다른 이름"):
            self.run_install()
        self.assertEqual((current / "keep.md").read_text(encoding="utf-8"), "user changes")
        self.assertFalse((current.parent / "square-company-test").exists())

    def test_legacy_install_appearing_during_confirmation_is_preserved(self):
        def confirm(_):
            self.related_install(metadata=json.dumps({"packageId": "company.skills.test"}))
            return "y"
        with self.assertRaisesRegex(installer.InstallError, "같은 스킬.*다른 이름"):
            self.run_install(interactive=True, yes=False, ask=confirm)
        root = self.project / ".claude/skills"
        self.assertFalse((root / "test").exists())
        self.assertEqual((root / "square-company-test/keep.md").read_text(encoding="utf-8"), "user changes")
        self.assertFalse(list(root.glob(".square-install-*")))

    def test_legacy_install_appearing_during_retry_cleans_only_staging(self):
        error = PermissionError("lock"); error.winerror = 32
        def competing_install(_):
            self.related_install(metadata=json.dumps({"packageId": "company.skills.test"}))
        with patch.object(installer.os, "rename", side_effect=error) as rename, patch.object(installer.time, "sleep", competing_install):
            with self.assertRaisesRegex(installer.InstallError, "같은 스킬.*다른 이름"):
                self.run_install()
        self.assertEqual(rename.call_count, 1)
        root = self.project / ".claude/skills"
        self.assertFalse((root / "test").exists())
        self.assertEqual((root / "square-company-test/keep.md").read_text(encoding="utf-8"), "user changes")
        self.assertFalse(list(root.glob(".square-install-*")))

    def test_safe_standalone_name_is_bounded_and_rejects_devices(self):
        for name in ("a" * 65, "../escape", "x/y", "x\\y", "Other", "x--y", "con", "nul", "com1", "lpt9"):
            with self.subTest(name=name):
                self.files["SKILL.md"] = f"---\nname: {name}\ndescription: test\n---\n".encode()
                self.write_package()
                with self.assertRaises(installer.InstallError):
                    self.run_install()
                self.assertFalse((self.project / ".claude").exists())

    def test_project_installs_only_manifest_files(self):
        result = self.run_install()
        target = self.project / ".claude/skills/test"
        self.assertEqual(Path(result["target"]), target)
        self.assertEqual(result["packageId"], "test")
        self.assertEqual({x.relative_to(target).as_posix() for x in target.rglob("*") if x.is_file()}, set(self.files) | {"PACKAGE_CONTENTS.json"})
        for name, data in self.files.items():
            self.assertEqual((target / name).read_bytes(), data)
        self.assertFalse(list(target.parent.glob(".square-install-*")))
        self.assertIn(str(target), self.stdout.getvalue())
        self.assertFalse((self.home / ".claude").exists())

    def test_user_uses_synthetic_home_and_keeps_settings(self):
        config = self.home / ".claude"
        config.mkdir()
        settings = config / "settings.json"
        settings.write_text('{"keep":"unchanged"}', encoding="utf-8")
        result = self.run_install(scope="user", project_dir=None)
        self.assertEqual(Path(result["target"]), config / "skills/test")
        self.assertEqual(settings.read_text(encoding="utf-8"), '{"keep":"unchanged"}')
        self.assertFalse((self.project / ".claude").exists())

    def test_user_honors_absolute_config_dir(self):
        custom = self.root / "custom-claude"
        result = self.run_install(scope="user", project_dir=None, environ={"CLAUDE_CONFIG_DIR": str(custom)})
        self.assertEqual(Path(result["target"]), custom / "skills/test")
        self.assertFalse((self.home / ".claude").exists())

    def test_relative_config_dir_rejected(self):
        with self.assertRaisesRegex(installer.InstallError, "절대 경로"):
            self.run_install(scope="user", project_dir=None, environ={"CLAUDE_CONFIG_DIR": "relative-profile"})
        self.assertFalse((self.home / ".claude").exists())

    def test_scope_required_even_with_yes(self):
        with self.assertRaisesRegex(ValueError, "설치 범위"):
            self.run_install(scope=None)
        self.assertFalse((self.project / ".claude").exists())

    def test_confirmation_required_noninteractive(self):
        with self.assertRaisesRegex(installer.InstallError, "--yes"):
            self.run_install(yes=False)
        self.assertFalse((self.project / ".claude").exists())

    def test_interactive_scope_and_confirmation(self):
        replies = iter(["1", "y"])
        with patch.object(installer, "select_scope", wraps=helper.select_scope) as selection:
            self.run_install(scope=None, interactive=True, yes=False, ask=lambda _: next(replies))
        self.assertEqual(selection.call_count, 1)

    def test_interactive_cancel_does_not_create_profile(self):
        with self.assertRaisesRegex(installer.InstallError, "취소"):
            self.run_install(interactive=True, yes=False, ask=lambda _: "n")
        self.assertFalse((self.project / ".claude").exists())

    def test_dry_run_no_writes_or_confirmation(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        result = self.run_install(dry_run=True, yes=False)
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")))

    def test_existing_target_preserved(self):
        target = self.project / ".claude/skills/test"
        target.mkdir(parents=True)
        (target / "keep.md").write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallError, "덮어쓰지"):
            self.run_install()
        self.assertEqual(list(target.iterdir()), [target / "keep.md"])
        self.assertEqual((target / "keep.md").read_text(encoding="utf-8"), "existing")

    def test_changed_content_rejected_before_writes(self):
        (self.package / "references/info.md").write_bytes(b"tampered")
        with self.assertRaisesRegex(installer.InstallError, "배포 당시"):
            self.run_install()
        self.assertFalse((self.project / ".claude").exists())

    def test_traversal_paths_rejected(self):
        for path in ("../escape", "/escape", "C:/escape", "x\\escape", "x//escape", "AUX.txt", "x./bad"):
            with self.subTest(path=path):
                self.manifest["files"][path] = "0" * 64
                self.write_manifest()
                with self.assertRaises(installer.InstallError):
                    self.run_install()
                del self.manifest["files"][path]
        self.assertFalse((self.project / ".claude").exists())

    def test_case_colliding_paths_rejected(self):
        self.manifest["files"]["skill.md"] = hashlib.sha256(self.files["SKILL.md"]).hexdigest()
        self.write_manifest()
        with self.assertRaisesRegex(installer.InstallError, "중복 경로"):
            self.run_install()

    def test_unexpected_skill_name_rejected(self):
        self.files["SKILL.md"] = b"---\nname: other-skill\ndescription: test\n---\n"
        self.write_package()
        with self.assertRaisesRegex(installer.InstallError, "packageId"):
            self.run_install()

    def test_legacy_package_id_with_plain_name_remains_installable(self):
        self.files["ai-square.json"] = json.dumps({"packageId": "company.skills.test"}).encode()
        self.write_package()
        result = self.run_install()
        self.assertEqual(result["packageId"], "company.skills.test")
        self.assertEqual(Path(result["target"]), self.project / ".claude/skills/test")

    def test_plain_id_cannot_install_a_legacy_or_other_name(self):
        for name in ("square-company-test", "different"):
            with self.subTest(name=name):
                self.files["SKILL.md"] = f"---\nname: {name}\ndescription: synthetic\n---\n".encode()
                self.write_package()
                with self.assertRaisesRegex(installer.InstallError, "packageId"):
                    self.run_install()
                self.assertFalse((self.project / ".claude").exists())

    def test_reinstall_with_old_or_new_id_preserves_actual_user_edits(self):
        result = self.run_install()
        target = Path(result["target"])
        (target / "references/info.md").write_text("personal workflow", encoding="utf-8")
        before = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
        for package_id in ("test", "company.skills.test"):
            with self.subTest(package_id=package_id):
                self.files["ai-square.json"] = json.dumps({"packageId": package_id}).encode()
                self.write_package()
                with self.assertRaisesRegex(installer.InstallError, "덮어쓰지"):
                    self.run_install()
                self.assertEqual(before, {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()})
        self.assertEqual([p.name for p in target.parent.iterdir()], ["test"])

    def test_reparse_parent_and_source_rejected(self):
        original = Path.lstat
        for unsafe in (self.project, self.package / "SKILL.md"):
            with self.subTest(unsafe=unsafe):
                def fake(path, *args, **kw):
                    result = original(path, *args, **kw)
                    if path == unsafe:
                        return types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
                    return result
                with patch.object(Path, "lstat", fake):
                    with self.assertRaisesRegex(installer.InstallError, "재분석"):
                        self.run_install()
        self.assertFalse((self.project / ".claude").exists())

    def test_final_collision_keeps_existing_and_cleans_only_staging(self):
        target = self.project / ".claude/skills/test"
        def collision(source, destination):
            target.mkdir()
            (target / "keep.md").write_text("another installer", encoding="utf-8")
            raise FileExistsError("simulated atomic collision")
        with patch.object(installer.os, "rename", collision):
            with self.assertRaises(FileExistsError):
                self.run_install()
        self.assertEqual((target / "keep.md").read_text(encoding="utf-8"), "another installer")
        self.assertFalse(list(target.parent.glob(".square-install-*")))

    def test_transient_windows_lock_retries_same_rename(self):
        real = installer.os.rename
        error = PermissionError('temporary lock'); error.winerror = 5
        calls = []
        def rename(source, target):
            calls.append((source, target))
            if len(calls) == 1:
                raise error
            return real(source, target)
        with patch.object(installer.os, 'rename', rename), patch.object(installer.time, 'sleep') as wait:
            result = self.run_install()
        self.assertEqual(result['status'], 'installed')
        self.assertEqual(calls[0], calls[1])
        wait.assert_called_once_with(0.1)

    def test_persistent_windows_denial_stops_without_target(self):
        error = PermissionError('denied'); error.winerror = 5
        with patch.object(installer.os, 'rename', side_effect=error) as rename, patch.object(installer.time, 'sleep'):
            with self.assertRaises(PermissionError):
                self.run_install()
        self.assertEqual(rename.call_count, 3)
        root = self.project / '.claude/skills'
        self.assertFalse((root / 'test').exists())
        self.assertFalse(list(root.glob('.square-install-*')))

    def test_collision_during_retry_preserves_other_install(self):
        target = self.project / '.claude/skills/test'
        error = PermissionError('lock'); error.winerror = 32
        def competing_install(_):
            target.mkdir(); (target / 'keep.md').write_text('keep', encoding='utf-8')
        with patch.object(installer.os, 'rename', side_effect=error) as rename, patch.object(installer.time, 'sleep', competing_install):
            with self.assertRaises(installer.InstallError):
                self.run_install()
        self.assertEqual(rename.call_count, 1)
        self.assertEqual((target / 'keep.md').read_text(encoding='utf-8'), 'keep')


if __name__ == "__main__":
    unittest.main(verbosity=2)
