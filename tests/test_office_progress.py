"""Owned helper transport tests; never opens a real Office document or approves one."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent import business_safety, office_progress as progress


class ProgressTests(unittest.TestCase):
    def child(self, code, **kwargs):
        return progress.run_helper([sys.executable, '-I', '-X', 'utf8', '-c', code], b'{}',
                                   progress=kwargs.pop('progress', progress.Progress(enabled=False)), **kwargs)

    def test_stage_messages_do_not_pollute_json_or_echo_stderr(self):
        reporter = progress.Progress()
        stderr = io.StringIO()
        code = ("import sys; sys.stdin.read(); print('PRIVATE document text',file=sys.stderr); "
                "print('CA_OFFICE_STAGE:open',file=sys.stderr,flush=True); "
                "print('CA_OFFICE_STAGE:read',file=sys.stderr,flush=True); print('{\"ok\":true}')")
        with contextlib.redirect_stderr(stderr):
            result = self.child(code, timeout=5, progress=reporter)
        self.assertEqual({'ok': True}, json.loads(result.stdout))
        self.assertEqual(b'', result.stderr)
        self.assertNotIn('PRIVATE', stderr.getvalue())
        self.assertIn('문서 여는 중', stderr.getvalue())
        self.assertEqual('read', reporter.finish()['lastStage'])

    def test_confirmation_start_and_wait_deadlines_are_distinct(self):
        with self.assertRaises(progress.HelperTimeout) as startup:
            self.child('import time; time.sleep(10)', timeout=5, startup_timeout=.15)
        self.assertFalse(startup.exception.ready)
        # Give interpreter startup ample time; the much shorter response limit
        # applies only after this synthetic Shown marker, not process creation.
        code = "import sys,time; print('CA_OFFICE_STAGE:confirmation_wait',file=sys.stderr,flush=True); time.sleep(10)"
        with self.assertRaises(progress.HelperTimeout) as waiting:
            self.child(code, timeout=.15, startup_timeout=5)
        self.assertTrue(waiting.exception.ready)

    def test_repeated_ready_marker_does_not_extend_deadline(self):
        code = ("import sys,time\nfor i in range(50):\n"
                " print('CA_OFFICE_STAGE:confirmation_wait',file=sys.stderr,flush=True)\n time.sleep(.1)")
        started = time.monotonic()
        with self.assertRaises(progress.HelperTimeout):
            self.child(code, timeout=.2, startup_timeout=5)
        self.assertLess(time.monotonic() - started, 3)

    def test_read_stall_keeps_last_stage_and_does_not_return_partial_content(self):
        reporter = progress.Progress(enabled=False)
        code = "import sys,time; print('CA_OFFICE_STAGE:open',file=sys.stderr,flush=True); print('PRIVATE',flush=True); time.sleep(10)"
        with self.assertRaises(progress.HelperTimeout) as error:
            self.child(code, timeout=.4, progress=reporter)
        self.assertEqual('open', reporter.finish()['lastStage'])
        self.assertIsNone(error.exception.output)
        self.assertIsNone(error.exception.stderr)

    def test_stdout_and_stderr_limits(self):
        for code in ("import sys; sys.stdout.write('x'*2200000)", "import sys; sys.stderr.write('x'*70000)"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.child(code, timeout=5)

    def test_marker_only_does_not_grant_approval(self):
        # confirm_action must still require an explicit approved:true result.
        completed = subprocess.CompletedProcess([], 0, b'{"approved":false}')
        completed.ready = True
        reporter = progress.Progress(enabled=False)
        with patch.object(business_safety, 'windows_powershell', return_value=Path(sys.executable)), \
             patch.object(progress, 'run_helper', return_value=completed):
            self.assertFalse(business_safety.confirm_action('fixture', 'metadata only', progress=reporter))

    def test_approval_without_shown_receipt_is_rejected(self):
        completed = subprocess.CompletedProcess([], 0, b'{"approved":true}')
        completed.ready = False
        reporter = progress.Progress(enabled=False)
        with patch.object(business_safety, 'windows_powershell', return_value=Path(sys.executable)), \
             patch.object(progress, 'run_helper', return_value=completed):
            self.assertFalse(business_safety.confirm_action('fixture', 'metadata only', progress=reporter))
        self.assertEqual('confirmation_unavailable', reporter.failure_code)

    def test_confirmation_has_fixed_startup_and_response_limits(self):
        for ready, code in ((False, 'confirmation_start_timeout'), (True, 'confirmation_wait_timeout')):
            reporter = progress.Progress(enabled=False)
            with patch.object(business_safety, 'windows_powershell', return_value=Path(sys.executable)), \
                 patch.object(progress, 'run_helper', side_effect=progress.HelperTimeout([], 30, ready=ready)) as child:
                self.assertFalse(business_safety.confirm_action('fixture', 'metadata only', progress=reporter))
            self.assertEqual(code, reporter.failure_code)
            self.assertEqual(30, child.call_args.kwargs['startup_timeout'])
            self.assertEqual(300, child.call_args.kwargs['timeout'])

    def test_progress_has_only_fixed_stages_and_is_idempotent(self):
        reporter = progress.Progress(enabled=False)
        reporter.begin('PRIVATE path')
        reporter.begin('read')
        reporter.begin('read')
        first = reporter.finish()
        reporter.begin('close')
        self.assertEqual(first, reporter.finish())
        self.assertEqual({'read'}, set(first['stageMs']))

    def test_cli_bootstrap_timing_is_numeric_only(self):
        with patch.dict(os.environ, {'COMPANY_AGENT_OFFICE_BOOTSTRAP_MS': '12'}), \
             patch.object(progress, '_cli_progress', None), contextlib.redirect_stderr(io.StringIO()):
            progress.begin_cli()
            result = progress.cli_progress().finish()
        self.assertEqual(12, result['stageMs']['bootstrap'])
        self.assertGreaterEqual(result['totalMs'], 12)

    def test_helpers_are_silent_without_progress_flag(self):
        with patch.dict(os.environ, {'COMPANY_AGENT_OFFICE_PROGRESS': ''}), contextlib.redirect_stderr(io.StringIO()) as err:
            progress.helper_stage('open')
        self.assertEqual('', err.getvalue())


if __name__ == '__main__': unittest.main()
