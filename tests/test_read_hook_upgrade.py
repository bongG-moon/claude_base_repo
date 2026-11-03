"""Exercise legacy and no-Read-hook installs in an isolated synthetic profile."""
import hashlib
import json
from pathlib import Path

from tests.test_version_cleanup_integration import (
    VersionCleanupIntegrationTests,
    hashes,
    write_json,
)


class ReadHookUpgradeTests(VersionCleanupIntegrationTests):
    def bundle_with_hook(self, version, matcher, *, entry):
        bundle = super().bundle(version)
        plugin = bundle / "payload/core/plugin"
        write_json(plugin / "hooks/hooks.json", {"hooks": {"PreToolUse": [{
            "matcher": matcher,
            "hooks": [{"type": "command", "command": "powershell.exe", "args": [
                "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                "${CLAUDE_PLUGIN_ROOT}/scripts/Invoke-CompanyAgent.ps1",
                "-Mode", "Hook", "-Event", "PreToolUse",
            ]}],
        }]}})
        if entry:
            (plugin / "scripts/read_hook.py").write_text("# synthetic entry\n", encoding="utf-8")
        manifest_path = bundle / "bundle-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = [
            {"path": p.relative_to(bundle).as_posix(), "length": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(bundle.rglob("*"))
            if p.is_file() and p != manifest_path
        ]
        write_json(manifest_path, manifest)
        return bundle

    def test_legacy_update_failure_and_no_read_reapply_preserve_user_data(self):
        legacy = self.bundle_with_hook("9.1.0", "^Read$", entry=True)
        no_read = self.bundle_with_hook("9.2.0", "^Bash$", entry=True)
        personal_before = hashes(self.state)

        installed = self.install(legacy)
        self.assertEqual("installed", installed.get("result", {}).get("status"), installed)
        old_launcher = self.versions / "9.1.0/read-hook.cmd"
        self.assertTrue(old_launcher.is_file())
        old_bytes = old_launcher.read_bytes()

        # A failed legacy reapply must roll its mutable launcher back exactly.
        prior_custom_launcher = b"fixture previous launcher; keep on failure\r\n"
        old_launcher.write_bytes(prior_custom_launcher)
        (self.root / "fail-update").write_text("fixture", encoding="utf-8")
        failed_reapply = self.install(legacy)
        self.assertIn("error", failed_reapply)
        self.assertEqual(prior_custom_launcher, old_launcher.read_bytes())
        self.assertEqual(personal_before, hashes(self.state))
        (self.root / "fail-update").unlink()
        old_launcher.write_bytes(old_bytes)

        (self.root / "fail-update").write_text("fixture", encoding="utf-8")
        failed = self.install(no_read)
        self.assertIn("error", failed)
        self.assertFalse((self.versions / "9.2.0").exists())
        self.assertEqual(old_bytes, old_launcher.read_bytes())
        self.assertEqual(personal_before, hashes(self.state))
        registration = json.loads((self.local / "CompanyAgent/installations/user/company-agent-install.json").read_text(encoding="utf-8-sig"))
        self.assertEqual("9.1.0", registration["coreVersion"])
        (self.root / "fail-update").unlink()

        updated = self.install(no_read)
        self.assertEqual("updated", updated.get("result", {}).get("status"), updated)
        new_launcher = self.versions / "9.2.0/read-hook.cmd"
        self.assertFalse(new_launcher.exists(), "Unregistered Read hook must not create a launcher")
        self.assertEqual(old_bytes, old_launcher.read_bytes())
        self.assertEqual(personal_before, hashes(self.state))

        # A same-version reapply must not touch an unrelated pre-existing file.
        new_launcher.write_bytes(b"user-owned fixture; preserve exactly\r\n")
        reapplied = self.install(no_read)
        self.assertEqual("reapplied", reapplied.get("result", {}).get("status"), reapplied)
        self.assertEqual(b"user-owned fixture; preserve exactly\r\n", new_launcher.read_bytes())
        self.assertEqual(old_bytes, old_launcher.read_bytes())
        self.assertEqual(personal_before, hashes(self.state))

    def test_read_matcher_without_fast_path_does_not_create_launcher(self):
        no_entry = self.bundle_with_hook("9.1.0", "^Read$", entry=False)
        installed = self.install(no_entry)
        self.assertEqual("installed", installed.get("result", {}).get("status"), installed)
        self.assertFalse((self.versions / "9.1.0/read-hook.cmd").exists())
