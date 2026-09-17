"""Bounded local hook evidence, not telemetry or proof of model understanding.

Only event metadata is retained in the existing session record. Never persist
payloads, prompt/document text, exception messages, or complete output context.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import atomic_write_json
from .state import _locked_session


def record_hook(root: Path, session_id: str, event: str, status: str, elapsed_ms: int,
                *, runtime_text: str = '', error_type: str = '', output_chars: int | None = None) -> None:
    if not session_id or event not in {'SessionStart', 'UserPromptSubmit'}:
        return
    if status not in {'started', 'output-produced', 'failed'}:
        return
    try:
        runtime = json.loads(runtime_text).get('company_agent_runtime', {}) if runtime_text else {}
        index = runtime.get('skillIndex', {})
        evidence = {'status': status, 'elapsedMs': max(0, int(elapsed_ms)),
                    'hostReceipt': 'not-observable', 'modelApplied': 'not-observable',
                    'contextChars': max(0, output_chars) if type(output_chars) is int else len(runtime_text)}
        revision = index.get('revision', '')
        if isinstance(revision, str) and re.fullmatch(r'[a-f0-9]{64}', revision):
            evidence['catalogRevision'] = revision
        if index.get('mode') in {'inline', 'pages', 'reuse'}:
            evidence['indexMode'] = index['mode']
        evidence['candidateNames'] = [c['name'] for g in runtime.get('taskSkills', {}).get('groups', [])
                                      for c in g.get('candidates', []) if isinstance(c.get('name'), str)
                                      and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,159}', c['name'])][:16]
        if runtime.get('contextStatus') or runtime.get('skillSelection', {}).get('catalog', {}).get('status') in {'unavailable', 'incomplete'}:
            evidence['discoveryStatus'] = 'incomplete'
        elif runtime_text:
            evidence['discoveryStatus'] = 'available' if index else 'not-produced'
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', error_type):
            evidence['errorType'] = error_type
        with _locked_session(session_id, root) as (state, path):
            existing = state.get('hookDiagnostics', {})
            existing = existing if isinstance(existing, dict) else {}
            # Latest two events only; no accumulating turn/transcript log.
            state['hookDiagnostics'] = {k: v for k, v in existing.items() if k in {'SessionStart', 'UserPromptSubmit'}}
            state['hookDiagnostics'][event] = evidence
            atomic_write_json(path, state)
    except Exception:
        # Observability must never block work, permissions, or real hook output.
        return
