"""The legacy source Read fast path retains native permissions for all files."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import read_hook


class ReadHookTests(unittest.TestCase):
    def run_main(self, payload, *, raw=False):
        output = io.StringIO()
        value = payload if raw else json.dumps(payload, ensure_ascii=False)
        with patch.object(sys, "stdin", io.StringIO(value)), \
                patch.object(read_hook, "fallback", return_value=17) as fallback, \
                contextlib.redirect_stdout(output):
            result = read_hook.main()
        return result, output.getvalue(), fallback

    def test_text_image_and_pdf_reads_keep_native_permissions_and_skip_fallback(self):
        for suffix in ("txt", "md", "png", "JPG", "pdf", "svg"):
            with self.subTest(suffix=suffix):
                result, text, fallback = self.run_main({
                    "tool_name": "Read", "tool_input": {"file_path": f"C:/가상/문서.{suffix}"}
                })
                self.assertEqual(0, result)
                self.assertEqual({}, json.loads(text))
                fallback.assert_not_called()

    def test_invalid_input_uses_fallback_once_without_guessing(self):
        for payload in ("not json", "[]", '{"tool_name":"Read","tool_input":{}}',
                        '{"tool_name":"Bash","tool_input":{"file_path":"a"}}'):
            with self.subTest(payload=payload):
                result, text, fallback = self.run_main(payload, raw=True)
                self.assertEqual(17, result)
                self.assertEqual("", text)
                fallback.assert_called_once_with(payload)

    def test_unsupported_python_uses_the_same_recovery_path_once(self):
        payload = '{"tool_name":"Read","tool_input":{"file_path":"a.png"}}'
        with patch.object(sys, "version_info", (3, 10, 0)):
            result, text, fallback = self.run_main(payload, raw=True)
        self.assertEqual(17, result)
        self.assertEqual("", text)
        fallback.assert_called_once_with(payload)

    def test_fallback_forwards_utf8_and_exit_code_without_shell_or_retry(self):
        payload = '{"tool_name":"Read","tool_input":{"file_path":"한글.png"}}'
        with patch.object(read_hook.subprocess, "run", return_value=subprocess.CompletedProcess([], 5)) as run:
            self.assertEqual(5, read_hook.fallback(payload))
        run.assert_called_once()
        self.assertEqual(payload.encode("utf-8"), run.call_args.kwargs["input"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_launcher_failure_is_not_exposed_and_not_retried(self):
        errors = io.StringIO()
        with patch.object(read_hook.subprocess, "run", side_effect=PermissionError("private path")) as run, \
                contextlib.redirect_stderr(errors):
            self.assertEqual(2, read_hook.fallback("private payload"))
        run.assert_called_once()
        self.assertNotIn("private path", errors.getvalue())
        self.assertNotIn("private payload", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
