"""On-demand, read-only map of this folder's three harness areas.

No model, shell, MCP connection, transcript crawl, cache write or configuration
mutation. A settings declaration is NOT evidence of host loading/execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

from .skill_registry import (_no_reparse, _json_read, _project_directories,
                             _installed_plugins, _frontmatter_field, _plugin_skill_roots, _resolution)

MAX_ENTRIES = 100
MAX_ROWS = 180  # Per area; folder/JSON limits apply before rendering as well.
MAX_ENCODED_ITEMS = 600_000  # Keep JSON + escaped HTML below the UI response cap.
AREAS = {
    'company': ('회사 공통', '회사가 배포한 업무 기준과 기능 · 여기서는 읽기 전용'),
    'personal': ('개인 전체', '내 Claude 설정과 개인 자료 · 여러 프로젝트에서 참고'),
    'project': ('이 프로젝트', '현재 폴더의 지침과 전용 자료 · 공유 파일과 나만 사용을 구분'),
}
STATUS = {'enabled': '설정 켜짐', 'available': '사용 가능', 'defined': '정의 발견',
          'disabled': '꺼짐 / 제외', 'unknown': '확인 필요', 'missing': '없음',
          'choice': '선택 필요', 'manual': '명시 호출만', 'draft': '초안 / 미적용'}


def _text(value, limit=300):
    return ' '.join(str(value or '').replace('\x00', '').split())[:limit]


class _Reader:
    def __init__(self):
        self.warnings = []

    def warn(self, path, reason='읽기 제한 또는 잘못된 형식'):
        message = f'{reason}: {path}'
        if message not in self.warnings and len(self.warnings) < 30:
            self.warnings.append(message)

    def json(self, path):
        try:
            return _json_read(path) or {}
        except (OSError, ValueError, UnicodeError, RecursionError):
            self.warn(path)
            return None

    def exists(self, path, *, directory=False):
        try:
            _no_reparse(path)
            return path.is_dir() if directory else path.is_file()
        except (OSError, ValueError):
            self.warn(path)
            return False

    def files(self, root, *, depth=0, suffix='.md'):
        """At most 100 directory entries total, no links, no arbitrary crawl."""
        pending, entries = [(root, 0)], 0
        while pending:
            folder, level = pending.pop(0)
            try:
                _no_reparse(folder)
                if not folder.is_dir():
                    continue
                with os.scandir(folder) as stream:
                    for entry in stream:
                        entries += 1
                        if entries > MAX_ENTRIES:
                            self.warn(root, '목록 상한 도달 · 일부만 표시')
                            return
                        path = Path(entry.path)
                        try:
                            _no_reparse(path)
                        except (OSError, ValueError):
                            self.warn(path, '연결 경로는 탐색하지 않음')
                            continue
                        if entry.is_file(follow_symlinks=False) and entry.name.endswith(suffix):
                            yield path
                        elif level < depth and entry.is_dir(follow_symlinks=False) and not entry.name.startswith('.'):
                            pending.append((path, level + 1))
            except (OSError, ValueError):
                self.warn(folder)

    def header(self, path):
        # Never retain/export the body, MCP commands, env or credential values.
        try:
            _no_reparse(path)
            with path.open('rb') as stream:
                raw = stream.read(16_384)
            raw = raw.removeprefix(b'\xef\xbb\xbf')
            if not re.search(br'\r?\n---(?:\r?\n|$)', raw[3:]) or not raw.startswith(b'---'):
                return {}
            return {key: _frontmatter_field(raw, key) for key in ('name', 'title', 'status', 'disable-model-invocation')}
        except (OSError, ValueError, UnicodeError):
            self.warn(path)
            return {}


def discover_registration(project, config, registrations, reader, installed):
    """Bounded installer records, matched to the current native plugin/profile."""
    files = [registrations / 'user/company-agent-install.json']
    files += [p for p in reader.files(registrations / 'projects', depth=1, suffix='.json')
              if p.name == 'company-agent-install.json']
    native = reader.json(config / 'plugins/installed_plugins.json') or {}
    plugin_records = native.get('plugins', {})
    if not isinstance(plugin_records, dict):
        return None, None
    choices = []
    for file in files:
        value = reader.json(file)
        if not value or value.get('schemaVersion') != 1 or value.get('enabled') is False:
            continue
        try:
            if Path(value.get('claudeConfigRoot', '')).absolute() != config:
                continue
            if ('claudeConfigDirOverride' in value and
                    value['claudeConfigDirOverride'] != bool(os.environ.get('CLAUDE_CONFIG_DIR'))):
                continue
            root = Path(value['userStateRoot'])
            if not root.is_absolute():
                continue
            _no_reparse(root)
            rank = 0
            if value.get('scope') == 'Project':
                target = Path(value['projectRoot'])
                if not target.is_absolute() or not project.is_relative_to(target):
                    continue
                rank = len(target.parts)
            elif value.get('scope') != 'User':
                continue
            plugin_id = value.get('pluginId', 'company-agent@company-agent-local')
            match = next((p for pid, p, scope in installed if pid == plugin_id and
                          scope == ('project' if rank else 'personal')), None)
            if match is None or not reader.exists(match, directory=True):
                continue
            entries = plugin_records.get(plugin_id, [])
            if not isinstance(entries, list) or len(entries) > 100:
                reader.warn(file, '설치 등록 목록 확인 필요')
                continue
            matching = [e for e in entries if isinstance(e, dict) and e.get('installPath') and
                        Path(e['installPath']).absolute() == match and
                        e.get('version') == value.get('coreVersion') and
                        e.get('scope') == value.get('nativeClaudeScope', 'user' if not rank else 'local')]
            if len(matching) != 1:
                reader.warn(file, '설치 버전·범위 불일치')
                continue
            choices.append((rank, {**value, 'registrationsRoot': str(registrations)}, match))
        except (KeyError, TypeError, OSError, ValueError):
            reader.warn(file)
    if choices:
        rank = max(c[0] for c in choices)
        best = [c for c in choices if c[0] == rank]
        if len(best) == 1:
            return best[0][1:]
        reader.warn(registrations, '같은 범위의 설치 등록 중복 · 자동 선택 안 함')
    return None, None


def build_map(project: Path, *, config: Path | None = None, record=None,
              plugin: Path | None = None, registrations: Path | None = None,
              session_id: str | None = None):
    started = time.perf_counter()
    project = project.expanduser().absolute()
    config = Path(config or os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').absolute()
    for path in (project, config):
        _no_reparse(path)
    if not project.is_dir():
        raise ValueError('확인할 작업 폴더가 없습니다.')
    reader = _Reader()
    groups = {key: {'id': key, 'label': title, 'description': description, 'items': []}
              for key, (title, description) in AREAS.items()}
    encoded_items = 0

    def add(area, category, name, status, path=None, detail='', sharing='', **extra):
        nonlocal encoded_items
        rows = groups[area]['items']
        if len(rows) >= MAX_ROWS:
            reader.warn(area, '표시 상한 도달 · 일부만 표시')
            return
        item = {'category': category, 'name': _text(name), 'status': status,
                'statusLabel': STATUS[status], 'path': str(path) if path else None,
                'detail': _text(detail, 700), 'sharing': sharing, **extra}
        size = len(json.dumps(item, ensure_ascii=True))
        if encoded_items + size > MAX_ENCODED_ITEMS:
            reader.warn(area, '응답 크기 상한 도달 · 일부만 표시')
            return
        rows.append(item)
        encoded_items += size

    lineage = _project_directories(project, config, reader.warnings)
    installed = _installed_plugins(config, project, lineage, reader.warnings)
    if record is None:
        registrations = Path(registrations or os.environ.get('COMPANY_AGENT_REGISTRATIONS_ROOT') or
                             Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local/share') / 'CompanyAgent/installations')
        record, plugin = discover_registration(project, config, registrations, reader, installed)
    if record is not None:
        if (record.get('scope') not in {'User', 'Project'} or
                Path(record.get('claudeConfigRoot', '')).absolute() != config):
            raise ValueError('다른 사용자 설정의 설치 자료는 합치지 않습니다.')
        root = Path(record['userStateRoot'])
        if not root.is_absolute() or '..' in root.parts:
            raise ValueError('등록된 저장소의 절대경로가 필요합니다.')
        if record['scope'] == 'Project':
            target = Path(record.get('projectRoot') or '')
            if not target.is_absolute() or not project.is_relative_to(target):
                raise ValueError('다른 프로젝트의 저장소를 현재 폴더에 합치지 않습니다.')
        _no_reparse(root)
        if plugin:
            plugin = plugin.absolute()
            _no_reparse(plugin)
    else:
        root = None

    settings = [('personal', config / 'settings.json')]
    for folder in reversed(lineage):
        settings.extend([('project', folder / '.claude/settings.json'),
                         ('project', folder / '.claude/settings.local.json')])
    flags, flag_paths, hooks_off, settings_ok = {}, {}, False, True
    loaded_settings = []
    for area, path in settings:
        value = reader.json(path)
        if value is None:
            settings_ok = False
            add(area, '설정', path.name, 'unknown', path, '설정 파일을 읽지 못해 켜짐/꺼짐을 확정하지 않습니다.')
            continue
        if not reader.exists(path):
            continue
        loaded_settings.append((area, path, value))
        add(area, '설정', path.name, 'defined', path, '설정 파일 발견. 실행 중인 Claude가 수신했다는 의미는 아닙니다.',
            '나만 사용' if area == 'personal' or path.name == 'settings.local.json' else '폴더 공유 시 함께 전달 가능')
        overlay = value.get('enabledPlugins', {})
        if not isinstance(overlay, dict) or len(overlay) > 1024:
            reader.warn(path, '플러그인 활성 설정 형식 확인 필요')
            settings_ok = False
        else:
            for name, flag in overlay.items():
                if type(flag) is bool:
                    flags[name], flag_paths[name] = flag, path
        if type(value.get('disableAllHooks')) is bool:
            hooks_off = value['disableAllHooks']

    company_id = (record or {}).get('pluginId', 'company-agent@company-agent-local')
    active_company = bool(record and plugin and settings_ok and
                          any(pid == company_id and path == plugin for pid, path, _ in installed))
    add('company', '설치', 'Company Agent', 'enabled' if active_company else 'unknown', plugin,
        ('현재 폴더의 설치 등록과 플러그인 켜짐 설정을 대조했습니다. 버전 ' + _text(record.get('coreVersion')))
        if active_company else '현재 폴더에 활성화된 Company Agent 설치를 확정하지 못했습니다. 개발 소스가 있다고 설치된 것은 아닙니다.')

    # Installed plugin metadata + explicit disabled declarations. Do not inspect
    # unrelated projects or enumerate disabled plugin code.
    registry = reader.json(config / 'plugins/installed_plugins.json')
    registry_rows = registry.get('plugins', {}) if registry else {}
    if not isinstance(registry_rows, dict) or len(registry_rows) > 1024:
        registry_rows = {}
        reader.warn(config / 'plugins/installed_plugins.json')
    chosen = {pid: (path, scope) for pid, path, scope in installed}
    registered = {}
    for pid, entries in list(registry_rows.items())[:MAX_ENTRIES]:
        if not isinstance(entries, list):
            reader.warn(config / 'plugins/installed_plugins.json')
            continue
        for entry in entries[:MAX_ENTRIES]:
            if not isinstance(entry, dict):
                continue
            if entry.get('scope') == 'user':
                registered.setdefault(pid, 'personal')
            elif entry.get('scope') in {'local', 'project'} and isinstance(entry.get('projectPath'), str):
                candidate = Path(entry['projectPath'])
                if candidate.is_absolute() and project.is_relative_to(candidate):
                    registered[pid] = 'project'
    if len(set(flags) | set(chosen) | set(registered)) > MAX_ENTRIES:
        reader.warn(config, '플러그인 표시 상한 도달')
    for name in sorted(set(flags) | set(chosen) | set(registered))[:MAX_ENTRIES]:
        if name == company_id:
            if flags.get(name) is False:
                add('company', '설정', name, 'disabled', flag_paths.get(name), '현재 폴더의 설정에서 플러그인을 껐습니다.')
            continue
        native = chosen.get(name)
        area = native[1] if native else registered.get(name, 'project' if flag_paths.get(name) and flag_paths[name].is_relative_to(project) else 'personal')
        status = ('unknown' if not settings_ok else 'disabled' if flags.get(name) is False else
                  'enabled' if native and reader.exists(native[0], directory=True) else 'unknown')
        add(area, '플러그인', name, status, native[0] if native else flag_paths.get(name),
            '설치 등록·활성 설정 기준입니다. 현재 대화에서 로드/실행된 증거는 아닙니다.')

    def instructions(area, folder, sharing):
        paths = [folder / 'CLAUDE.md'] if area == 'personal' else [folder / 'CLAUDE.md', folder / 'CLAUDE.local.md', folder / '.claude/CLAUDE.md']
        rule_root = folder / 'rules' if area == 'personal' else folder / '.claude/rules'
        found = [p for p in paths if reader.exists(p)] + list(reader.files(rule_root, depth=2))
        for path in found:
            add(area, '지침', str(path.relative_to(folder)), 'defined', path,
                '지침 파일이 있습니다. 경로별 조건·@참조·본문의 실제 로드는 별도입니다.',
                '나만 사용' if path.name == 'CLAUDE.local.md' else sharing)
        return found

    instructions('personal', config, '나만 사용')
    found_project = []
    for folder in reversed(lineage):
        found_project += instructions('project', folder, '폴더 공유 시 함께 전달 가능')
    if not found_project:
        add('project', '지침', '프로젝트 CLAUDE.md / 규칙', 'missing', project / 'CLAUDE.md', '조회 중 자동 생성하지 않습니다.')

    def hooks(area, path, value, origin=''):
        events = value.get('hooks', {})
        if not isinstance(events, dict):
            reader.warn(path)
            return
        for name in list(events)[:40]:
            add(area, '후크', f'{origin} · {name}' if origin else name, 'disabled' if hooks_off else 'defined', path,
                'disableAllHooks 설정으로 꺼짐.' if hooks_off else '이벤트 정의만 발견했습니다. 명령·환경변수는 표시하거나 실행하지 않습니다.')

    disabled_mcp, disabled_mcpjson = set(), set()

    def mcp(area, path, value, sharing, *, project_file=False):
        servers = value.get('mcpServers', {})
        if not isinstance(servers, dict) or len(servers) > 100:
            reader.warn(path, 'MCP 목록 형식 또는 상한 확인 필요')
            return
        for name, spec in servers.items():
            off = (isinstance(spec, dict) and spec.get('disabled') is True) or name in (disabled_mcpjson if project_file else disabled_mcp)
            add(area, '도구 · MCP', name, 'disabled' if off else 'defined', path,
                '등록 정보만 확인했습니다. 연결·인증·도구 허용 상태는 이 화면에서 시험하지 않습니다.', sharing)

    for area, path, value in loaded_settings:
        hooks(area, path, value)
    # Native global config contains sensitive fields. Read only one known file,
    # return ONLY MCP names, never OAuth/env/arguments/URLs/project histories.
    custom_config = bool((record or {}).get('claudeConfigDirOverride', bool(os.environ.get('CLAUDE_CONFIG_DIR'))))
    native_config = config / '.claude.json' if custom_config else config.parent / '.claude.json'
    native = reader.json(native_config) or {}
    local = {}
    projects = native.get('projects', {})
    if isinstance(projects, dict):
        local = next((value for key, value in projects.items() if isinstance(key, str) and
                      os.path.normcase(key.replace('/', os.sep)) == os.path.normcase(str(project))), {})
    if not isinstance(local, dict):
        local = {}
    for value in [v for _, _, v in loaded_settings] + [local]:
        for field, target in [('disabledMcpServers', disabled_mcp), ('disabledMcpjsonServers', disabled_mcpjson)]:
            names = value.get(field, [])
            if isinstance(names, list):
                target.update(n for n in names[:100] if isinstance(n, str))
    mcp('personal', native_config, native, '나만 사용')
    mcp('project', native_config, local, '나만 사용 · 현재 폴더 전용')
    mcp_path = project / '.mcp.json'
    mcp('project', mcp_path, reader.json(mcp_path) or {}, '폴더 공유 시 함께 전달 가능', project_file=True)

    observation = {}
    if root and session_id:
        if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', session_id):
            raise ValueError('올바른 현재 대화 ID가 아닙니다.')
        state = reader.json(root / 'sessions' / (session_id + '.json')) or {}
        route = state.get('skillWorkflow') or {}
        if isinstance(route, dict) and route.get('project') == os.path.normcase(str(project)):
            observation = route

    if root:
        from .skill_registry import inventory_skills
        try:
            inv = inventory_skills(root, project_root=project, claude_root=config,
                                   plugin_root=plugin if active_company else None,
                                   knowledge_root=Path(record['knowledgeBaseRoot']) if active_company and record.get('knowledgeBaseRoot') else None,
                                   resource_record=record, metadata_cache=False)
            reader.warnings += inv['warnings'][:20]
            by_name = {}
            for skill in inv['skills']:
                by_name.setdefault(skill['name'].casefold(), []).append(skill)
            resolutions = {name: _resolution(name, candidates, inv['effectivePreferences'])
                           for name, candidates in by_name.items()}
            for skill in inv['skills']:
                resolution = resolutions[skill['name'].casefold()]
                preferred = resolution['status'] == 'selected' and resolution.get('selectedId') == skill['id']
                area = ('company' if skill['source'] in {'company', 'corporate'} or skill.get('origin') == company_id else
                        skill.get('storageScope') or ('project' if skill['source'] == 'project' else 'personal'))
                read = observation.get('readSkills') or {}
                observed = isinstance(read, dict) and read.get(skill['id']) == skill['sha256']
                sharing = {'company': '회사 배포 · 읽기 전용', 'corporate': '회사 배포 · 읽기 전용',
                           'personal': '나만 사용', 'user': '나만 사용 · 여러 프로젝트',
                           'project': '폴더 공유 시 함께 전달 가능'}.get(skill['source'], '별도 플러그인 제공')
                add(area, '스킬', skill['invocation'] or skill['name'],
                    'unknown' if not settings_ok and skill['source'] in {'plugin', 'company'} else
                    'choice' if resolution['status'] in {'unresolved', 'stale-choice'} else
                    'manual' if skill['explicitOnly'] else 'available', skill['path'],
                    '이 대화에서 동일 본문 로드 기록이 있습니다. 현재 요청에 적용했거나 성공했다는 뜻은 아닙니다.' if observed else
                    '목록에서 발견한 후보입니다. 모델이 선택해 본문을 읽었는지는 미확인입니다.',
                    sharing, observed=observed, preferred=preferred)
        except (OSError, ValueError, TypeError, KeyError):
            reader.warn(root, '스킬 목록 확인 실패 · 기존 설정 유지')
    else:
        # Native-only folders remain inspectable without inventing a Company
        # state root or treating the development checkout as an installation.
        for area, folder in [('personal', config / 'skills')] + [('project', p / '.claude/skills') for p in lineage]:
            for path in reader.files(folder, depth=1):
                if path.name == 'SKILL.md':
                    meta = reader.header(path)
                    add(area, '스킬', meta.get('name') or path.parent.name, 'defined', path, '로컬 스킬 정의. Company Agent 활성 목록은 미확인입니다.')

        for pid, installed_path, area in installed[:MAX_ENTRIES]:
            area = 'company' if pid == company_id else area
            manifest = reader.json(installed_path / '.claude-plugin/plugin.json') or {}
            for folder in _plugin_skill_roots(installed_path, manifest, reader.warnings):
                candidates = [folder] if reader.exists(folder) else list(reader.files(folder, depth=1))
                for path in candidates:
                    if path.name == 'SKILL.md':
                        meta = reader.header(path)
                        add(area, '스킬', pid.split('@')[0] + ':' + (meta.get('name') or path.parent.name), 'defined', path,
                            '켜진 플러그인에서 정의를 발견했습니다. Company Agent의 선택·사용 기록은 미확인입니다.')

    for pid, installed_path, area in installed[:MAX_ENTRIES]:
        if pid == company_id:
            if active_company:
                continue  # Company definitions are displayed below, once.
            area = 'company'
        hooks(area, installed_path / 'hooks/hooks.json', reader.json(installed_path / 'hooks/hooks.json') or {}, pid.split('@')[0])
        mcp(area, installed_path / '.mcp.json', reader.json(installed_path / '.mcp.json') or {}, '플러그인 제공')
        for path in reader.files(installed_path / 'agents'):
            add(area, '에이전트', pid.split('@')[0] + ':' + path.stem, 'defined', path, '켜진 플러그인에 포함된 에이전트 정의입니다.')
        for path in reader.files(installed_path / 'commands'):
            add(area, '명령', '/' + pid.split('@')[0] + ':' + path.stem, 'defined', path, '플러그인 명령 정의입니다. 실제 호출 가능 여부는 CLI에서 확인합니다.')

    if active_company:
        hooks('company', plugin / 'hooks/hooks.json', reader.json(plugin / 'hooks/hooks.json') or {})
        mcp('company', plugin / '.mcp.json', reader.json(plugin / '.mcp.json') or {}, '회사 배포 · 읽기 전용')
        policy = record.get('managedConfigPath')
        if policy:
            add('company', '회사 정책', '배포 업무 기준', 'defined' if reader.exists(Path(policy)) else 'missing', policy,
                'Company Agent의 회사 정책입니다. Claude의 OS/서버 관리 정책 전체를 뜻하지 않습니다.')
        knowledge = record.get('knowledgeBaseRoot')
        if knowledge:
            add('company', '기억 · 지식', '회사 지식 저장소', 'defined' if reader.exists(Path(knowledge), directory=True) else 'missing', knowledge,
                '검토·배포 자료. 실제 요청과 관련된 자료만 검색하며 공동 쓰기 저장소가 아닙니다.', '회사 배포 · 읽기 전용')

    if root:
        from .resource_scope import destinations
        try:
            stores = destinations(root, project, record)
        except (OSError, ValueError):
            stores = {}
            reader.warn(root, '개인/프로젝트 저장소를 확인하지 못함')
        for area, store in stores.items():
            if not store['available']:
                add(area, '저장소', '개인 자료', 'unknown', detail=store['notice'])
                continue
            folder = Path(store['stateRoot'])
            add(area, '저장소', 'Company Agent 개인 자료', 'defined' if reader.exists(folder, directory=True) else 'missing', folder,
                store['notice'] + ' 저장소가 없으면 아직 자료를 저장하지 않은 상태일 수 있습니다.', '나만 사용')
            for category, rel in [('기억 · 지식', 'memory/items'), ('기억 · 지식', 'knowledge/entries'), ('기억 · 지식', 'knowledge/overlays')]:
                for path in reader.files(folder / rel):
                    meta = reader.header(path)
                    status = {'active': 'available', 'draft': 'draft', 'inactive': 'disabled', 'deprecated': 'disabled'}.get(meta.get('status'), 'unknown')
                    add(area, category, meta.get('title') or path.stem, status, path,
                        '저장된 상태 기준입니다. 본문·대화 원문을 표시·내보내지 않으며 실제 검색·적용은 별도입니다.', '나만 사용')
            assets = reader.json(folder / 'assets/registry.json') or {}
            entries = assets.get('assets', [])
            if isinstance(entries, list):
                for item in entries[:MAX_ENTRIES]:
                    if isinstance(item, dict) and item.get('type') in {'script-tool', 'mcp'}:
                        status = 'available' if item.get('status') == 'active' else 'draft' if item.get('status') == 'candidate' else 'unknown'
                        add(area, '도구 · MCP', item.get('name'), status, folder / 'assets/registry.json',
                            '자산 등록 상태만 표시합니다. 도구 코드·MCP 연결·권한을 실행 검증하지 않습니다.', '나만 사용')
        learning_path = root / 'config/learning.json'
        learning = reader.json(learning_path)
        enabled = (learning == {} and not reader.exists(learning_path)) or learning == {'schemaVersion': 1, 'enabled': True}
        status = 'enabled' if enabled else 'disabled' if learning == {'schemaVersion': 1, 'enabled': False} else 'unknown'
        area = 'project' if record['scope'] == 'Project' else 'personal'
        add(area, '자동 학습', '업무 방식 학습', status, root / 'config/learning.json',
            '현재 설치의 저장소에서만 학습합니다. 화면의 범위 선택으로 바뀌지 않고 모델 자체를 훈련하지 않습니다.')
    add('personal', '기억 · 지식', 'Claude 자체 자동 기억', 'unknown', config / 'projects',
        'Company Agent 기억과 별개입니다. 다른 프로젝트의 기억은 탐색하지 않습니다. 실제 위치·활성 상태는 Claude의 /memory에서 확인하세요.', '나만 사용 · 프로젝트별 분리')
    for area, folder in [('personal', config / 'agents')] + [('project', p / '.claude/agents') for p in lineage] + ([('company', plugin / 'agents')] if active_company else []):
        for path in reader.files(folder):
            add(area, '에이전트', path.stem, 'defined', path, '에이전트 정의만 발견했습니다. 실제 위임 실행 여부는 미확인입니다.')
    for area, folder in [('personal', config / 'commands')] + [('project', p / '.claude/commands') for p in lineage] + ([('company', plugin / 'commands')] if active_company else []):
        for path in reader.files(folder):
            add(area, '명령', '/' + ('company-agent:' if area == 'company' else '') + path.stem, 'defined', path,
                '로컬 명령 정의입니다. 기본 내장 명령 전체 목록이나 실제 호출 성공 기록은 아닙니다.')
    for group in groups.values():
        group['items'].sort(key=lambda row: (row['category'], row['name'].casefold()))
        group['counts'] = {status: sum(r['status'] == status for r in group['items']) for status in STATUS}
    return {'schemaVersion': 1, 'project': str(project), 'configRoot': str(config),
            'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'elapsedMs': round((time.perf_counter() - started) * 1000), 'readOnly': True,
            'modelCalls': 0, 'groups': list(groups.values()), 'warnings': list(dict.fromkeys(reader.warnings))[:30],
            'observation': '현재 대화의 본문 로드 기록만 대조' if observation else '현재 대화의 사용 기록 미확인',
            'limits': [
                '이 화면은 설정·파일의 조회 시점 스냅샷입니다. 실행 중인 Claude의 실제 컨텍스트와 다를 수 있습니다.',
                '사용 가능은 실제 사용이 아닙니다. 스킬 본문 로드 기록도 업무 적용·정확성을 증명하지 않습니다.',
                '알려진 설정 위치와 현재 폴더 계보만 확인합니다. 다른 프로젝트, CLAUDE.md의 @참조, 조건부 규칙의 적용 여부는 탐색하지 않습니다.',
                '회사 서버/OS 관리 정책, 실행 시 지정한 옵션, 다른 프로필, MCP 연결·인증, 내장 도구 전체는 이 화면에서 확인하지 않습니다.',
                '설정 상속은 Company Agent의 로컬 탐색 범위 기준입니다. Claude 버전별 최종 적용은 /status · /skills · /hooks · /mcp · /memory에서 확인하세요.',
                'HTML에 로컬 경로와 항목 이름이 포함됩니다. 다른 사람에게 전달하기 전에 확인하세요. 새로고침은 Workspace에서만 가능합니다.'
            ]}
