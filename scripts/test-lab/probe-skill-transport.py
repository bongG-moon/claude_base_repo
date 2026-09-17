"""Real Claude host -> list-based preparation -> scripted native Skill load.

No external model, real document, installation or credentials. This verifies
transport and load receipts, NOT a model's autonomous choice. Uses a disposable
config/state/workspace. The skip-list scenario tries a harmless shell print
first and verifies the one-time redirect before loading the Skill. No real LLM.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

REPO = Path(__file__).resolve().parents[2]


def run(claude: Path, model: str, scenario: str = 'native-load') -> dict:
    observations = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            size = int(self.headers.get('Content-Length', 0))
            if size > 2_000_000:
                self.send_error(413)
                return
            data = json.loads(self.rfile.read(size))
            if 'count_tokens' in self.path:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"input_tokens":100}')
                return
            blocks = [b for m in data.get('messages', []) if isinstance(m.get('content'), list) for b in m['content']]
            text = '\n'.join(str(b.get('text', '')) for b in blocks)
            tools = [t['name'] for t in data.get('tools', [])]
            results = [b for b in blocks if b.get('type') == 'tool_result']
            redirected = any(b.get('is_error') and '[스킬 목록 확인 1회]' in json.dumps(b, ensure_ascii=False) for b in results)
            if tools:
                observations.append({'tools': tools, 'hasTaskCandidates': '"taskSkills"' in text,
                                     'briefBeforeRoute': 0 <= text.find('[업무 시작: 관련 스킬 우선]') < text.find('"company_agent_route"'),
                                     'hasOfficeCandidate': 'company-agent:office-reader' in text,
                                     'hasProvidedBody': '[선택된 스킬 본문 — 먼저 이 절차를 적용]' in text and 'Presentations.Open' in text,
                                     'hasReviewRedirect': redirected,
                                     'hasLoadedBody': 'Base directory for this skill:' in text and 'business office-read' in text})
            skip_scenario = scenario.startswith('skip-list')
            skip_first = bool(tools) and skip_scenario and not results
            invoke = bool(tools) and (not results or skip_scenario and len(results) == 1)
            tool_name = ('Write' if scenario == 'skip-list-write' else 'Bash') if skip_first else 'Skill'
            tool_input = ({'file_path': str(root / 'workspace/probe.txt'), 'content': 'unexpected write'} if tool_name == 'Write'
                          else {'command': "printf 'probe_unexpected_execution'"} if tool_name == 'Bash'
                          else {'skill': 'company-agent:office-reader'})
            content = ({'type': 'tool_use', 'id': 'toolu_probe_' + tool_name, 'name': tool_name, 'input': {}}
                       if invoke else {'type': 'text', 'text': ''})
            delta = ({'type': 'input_json_delta', 'partial_json': json.dumps(tool_input)}
                     if invoke else {'type': 'text_delta', 'text': '격리된 전달 검증 완료.'})
            reason = 'tool_use' if invoke else 'end_turn'
            message = {'id': 'msg_probe', 'type': 'message', 'role': 'assistant', 'model': data.get('model'),
                       'content': [], 'stop_reason': None, 'stop_sequence': None,
                       'usage': {'input_tokens': 100, 'output_tokens': 8}}
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if data.get('stream') else 'application/json')
            self.end_headers()
            if not data.get('stream'):
                message.update(content=[{**content, **({'input': tool_input} if invoke else {'text': '격리된 전달 검증 완료.'})}], stop_reason=reason)
                self.wfile.write(json.dumps(message).encode())
                return
            events = [('message_start', {'type': 'message_start', 'message': message}),
                      ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': content}),
                      ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': delta}),
                      ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
                      ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': reason, 'stop_sequence': None}, 'usage': {'output_tokens': 8}}),
                      ('message_stop', {'type': 'message_stop'})]
            for name, event in events:
                self.wfile.write(f'event: {name}\ndata: {json.dumps(event)}\n\n'.encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='ca-skill-transport-') as directory:
            root = Path(directory)
            for name in ('config', 'workspace', 'state', 'knowledge'):
                (root / name).mkdir()
            (root / 'knowledge/pack.json').write_text('{"version":"probe"}', encoding='utf-8')
            (root / 'empty-mcp.json').write_text('{"mcpServers":{}}', encoding='utf-8')
            env = {k: v for k, v in os.environ.items() if not k.startswith(('ANTHROPIC_', 'CLAUDE_', 'COMPANY_AGENT_'))}
            env.update({'ANTHROPIC_API_KEY': 'local-synthetic-not-a-secret',
                        'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{server.server_port}',
                        'CLAUDE_CONFIG_DIR': str(root / 'config'), 'COMPANY_AGENT_USER_STATE': str(root / 'state'),
                        'COMPANY_AGENT_KNOWLEDGE_BASE': str(root / 'knowledge'), 'COMPANY_AGENT_PYTHON': sys.executable,
                        'COMPANY_AGENT_SCOPE': 'IsolatedTransportTest', 'DISABLE_TELEMETRY': '1',
                        'DISABLE_ERROR_REPORTING': '1', 'DISABLE_AUTOUPDATER': '1', 'PYTHONUTF8': '1',
                        'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'})
            args = [str(claude), '-p', '--verbose', '--output-format', 'stream-json', '--include-hook-events',
                    '--setting-sources', '', '--settings', '{}', '--plugin-dir', str(REPO / 'company-agent-plugin'),
                    '--model', model, '--strict-mcp-config', '--mcp-config', str(root / 'empty-mcp.json'),
                    '--no-session-persistence', '--tools', 'Bash,Write,Read,Skill' if scenario.startswith('skip-list') else 'Read,Skill',
                    '--allowedTools', 'Skill,Bash,Write' if scenario.startswith('skip-list') else 'Skill']
            started = time.monotonic()
            result = subprocess.run(args, input='@PPT_검증전용_없는파일.pptx 내용을 파악해줘.',
                                    cwd=root / 'workspace', env=env, capture_output=True, encoding='utf-8', timeout=55)
            events = []
            for line in result.stdout.splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            init = next((e for e in events if e.get('subtype') == 'init'), {})
            # Filename only from the host's UUID, never from a model/tool response.
            import uuid
            sid = str(uuid.UUID(init['session_id']))
            state = json.loads((root / 'state/sessions' / f'{sid}.json').read_text(encoding='utf-8'))
            receipt = state.get('skillWorkflow', {}).get('lastBodyLoad', {})
            diagnostics = state.get('hookDiagnostics', {})
            checks = {'nativeRegistered': 'company-agent:office-reader' in init.get('skills', []),
                      'briefBeforeRouting': bool(observations) and observations[0]['briefBeforeRoute'],
                      'candidateDelivered': bool(observations) and observations[0]['hasTaskCandidates'],
                      'noUnobservedBodyInjection': bool(observations) and not observations[0]['hasProvidedBody'],
                      'nativeBodyReachedNextRequest': any(o['hasLoadedBody'] for o in observations),
                      'observedSkillLoad': receipt.get('tool') == 'Skill' and receipt.get('name') == 'office-reader',
                      'hooksProduced': all(diagnostics.get(e, {}).get('status') == 'output-produced' for e in ('SessionStart', 'UserPromptSubmit')),
                      'noBusinessMutation': state.get('mutationCount') == 0,
                      'boundedToolSet': all(set(o['tools']) <= {'Bash', 'Write', 'Read', 'Skill'} for o in observations)}
            if scenario.startswith('skip-list'):
                checks['hostBlockedFirstAction'] = any(o['hasReviewRedirect'] for o in observations)
                checks['reviewRecovered'] = state.get('skillWorkflow', {}).get('reviewCheckpoint', {}).get('status') == 'skill-loaded'
                checks['noUnintendedFile'] = not (root / 'workspace/probe.txt').exists()
            return {'kind': 'scripted-transport-not-model-behavior', 'scenario': scenario,
                    'ok': result.returncode == 0 and all(checks.values()),
                    'exitCode': result.returncode, 'elapsedSeconds': round(time.monotonic() - started, 2),
                    'modelLabelOnly': model, 'checks': checks}
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claude', required=True, type=Path, help='Existing Claude executable; no install or update')
    parser.add_argument('--model', default='HCP-LLM-Latest', help='Only a request label; response is always local and scripted')
    parser.add_argument('--scenario', choices=['native-load', 'skip-list', 'skip-list-write'], default='native-load')
    options = parser.parse_args()
    report = run(options.claude.resolve(strict=True), options.model, options.scenario)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    raise SystemExit(0 if report['ok'] else 1)
