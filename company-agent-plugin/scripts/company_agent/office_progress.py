"""Bounded Office stage telemetry: no document text, paths or persistent logs.

Stdout remains one result JSON. Stderr is short progress, not an error. A host
may buffer stderr; final diagnostics retain the same timings in that case.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time

LABELS = {
    'runtime': '설치·명령 준비 중',
    'request': '읽기 요청 확인 중',
    'conversation_consent': 'Claude 대화의 읽기 승인 확인 중',
    'confirmation_start': '확인 창 여는 중 (아직 승인 대기 전)',
    'confirmation_wait': '확인 창 표시됨 — 승인/취소를 기다립니다',
    'source_check': '원본 상태 확인 중',
    'dependencies': 'Office 연결 준비 중',
    'application': 'Office 실행 중',
    'open': '문서 여는 중',
    'permission': 'Office 권한 확인 중',
    'read': '내용·표·위치 읽는 중',
    'close': '읽은 문서 닫는 중 (저장 안 함)',
    'source_verify': '원본 변경 여부 확인 중',
}
HELPER_STAGES = frozenset({'dependencies', 'application', 'open', 'permission', 'read', 'close'})
PREFIX = b'CA_OFFICE_STAGE:'
_cli_progress = None


class Progress:
    def __init__(self, *, enabled=True):
        self.enabled = enabled
        self.started = self.changed = time.monotonic()
        self.stage = None
        self.timings = {}
        self.failure_code = None
        self.finished = False

    def begin(self, stage):
        if stage not in LABELS or stage == self.stage or self.finished:
            return
        now = time.monotonic()
        if self.stage:
            self.timings[self.stage] = self.timings.get(self.stage, 0) + round((now - self.changed) * 1000)
        self.stage, self.changed = stage, now
        if self.enabled:
            try:
                print('[문서 읽기] ' + LABELS[stage], file=sys.stderr, flush=True)
            except (OSError, UnicodeError):
                pass  # Progress presentation never authorizes or repeats a read.

    def finish(self):
        if not self.finished:
            now = time.monotonic()
            if self.stage:
                self.timings[self.stage] = self.timings.get(self.stage, 0) + round((now - self.changed) * 1000)
            self.total_ms = round((now - self.started) * 1000) + self.timings.get('bootstrap', 0)
            self.finished = True
        return {'lastStage': self.stage, 'stageMs': dict(self.timings), 'totalMs': self.total_ms}


def begin_cli():
    global _cli_progress
    _cli_progress = Progress()
    bootstrap = os.environ.get('COMPANY_AGENT_OFFICE_BOOTSTRAP_MS', '')
    if bootstrap.isascii() and bootstrap.isdigit() and 0 <= int(bootstrap) <= 300000:
        _cli_progress.timings['bootstrap'] = int(bootstrap)
    _cli_progress.begin('runtime')


def cli_progress():
    return _cli_progress or Progress()


def helper_stage(stage):
    if os.environ.get('COMPANY_AGENT_OFFICE_PROGRESS') == '1' and stage in HELPER_STAGES:
        # Only fixed ASCII markers cross the helper boundary, never COM errors.
        try:
            print((PREFIX + stage.encode('ascii')).decode('ascii'), file=sys.stderr, flush=True)
        except (OSError, UnicodeError):
            pass


class HelperTimeout(subprocess.TimeoutExpired):
    def __init__(self, command, timeout, *, ready=False):
        super().__init__(command, timeout)
        self.ready = ready


def run_helper(command, payload, *, timeout, progress, startup_timeout=None):
    """One owned child, bounded pipes/deadlines, no Office kill or retry.

For confirmation, the Shown event switches the startup deadline to the user
response deadline exactly once. Worker threads prevent blocked pipes from
stalling the supervising deadline. Non-protocol stderr is discarded.
"""
    started = time.monotonic()
    if len(payload) > 512 * 1024:
        raise ValueError('helper input limit')
    events = queue.Queue(maxsize=64)
    output = bytearray()
    env = dict(os.environ, COMPANY_AGENT_OFFICE_PROGRESS='1')
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def send(kind, value=None):
        # At most a handful of accepted stage markers; malformed streams cannot
        # accumulate unbounded events or prevent the supervisor timing out.
        try: events.put_nowait((kind, value))
        except queue.Full: pass

    def write_input():
        try:
            proc.stdin.write(payload)
            proc.stdin.flush()
        except OSError:
            send('io-error')
        finally:
            try: proc.stdin.close()
            except OSError: pass

    def read_output():
        try:
            while chunk := proc.stdout.read1(65536):
                if len(output) + len(chunk) > 2 * 1024 * 1024:
                    send('limit')
                    return
                output.extend(chunk)
        except OSError:
            send('io-error')
        finally:
            proc.stdout.close()
            send('stdout-done')

    def read_stages():
        seen, count = set(), 0
        allowed = {'confirmation_wait'} if startup_timeout is not None else HELPER_STAGES
        try:
            while line := proc.stderr.readline(256):
                count += len(line)
                if count > 65536:
                    send('limit')
                    return
                if line.startswith(PREFIX):
                    stage = line[len(PREFIX):].strip().decode('ascii', errors='replace')
                    if stage in allowed and stage not in seen:
                        seen.add(stage)
                        send('stage', stage)
        except OSError:
            send('io-error')
        finally:
            proc.stderr.close()
            send('stderr-done')

    threads = [threading.Thread(target=fn, daemon=True) for fn in (write_input, read_output, read_stages)]
    for thread in threads: thread.start()
    initial = startup_timeout if startup_timeout is not None else timeout
    deadline, ready, done = started + initial, False, set()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HelperTimeout(command, timeout if ready else initial, ready=ready)
            try: kind, value = events.get(timeout=min(remaining, .1))
            except queue.Empty: kind, value = None, None
            if kind == 'stage':
                progress.begin(value)
                if value == 'confirmation_wait' and not ready:
                    ready = True
                    deadline = time.monotonic() + timeout
            elif kind in {'stdout-done', 'stderr-done'}:
                done.add(kind)
            elif kind in {'limit', 'io-error'}:
                raise ValueError('invalid helper transport')
            if len(done) == 2 and proc.poll() is not None:
                result = subprocess.CompletedProcess(command, proc.returncode, bytes(output), b'')
                result.ready = ready
                return result
    finally:
        if proc.poll() is None:
            proc.kill()  # Our helper only, never taskkill/Office/user processes.
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: pass
        for thread in threads: thread.join(timeout=.1)
