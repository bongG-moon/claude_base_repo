"""Read declared installation names from local distribution bytes."""
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile
import zlib


MAX_DECLARATION_BYTES = 128 * 1024
LABELS = {'skill': '스킬명', 'mcp': 'MCP 선언 이름', 'plugin': '플러그인명'}


def identifier(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        return ''
    return value if re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]*', value) else ''


def skill_name(raw):
    if len(raw) > MAX_DECLARATION_BYTES:
        return ''
    text = raw.decode('utf-8-sig')
    header = re.match(r'\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)', text, re.S)
    if not header:
        return ''
    names = re.findall(r'^name[ \t]*:[ \t]*(.*?)[ \t]*\r?$', header.group(1), re.M)
    if len(names) != 1:
        return ''
    name = names[0]
    if len(name) >= 2 and name[0] == name[-1] and name[0] in {'"', "'"}:
        name = name[1:-1]
    return name if re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}', name) else ''


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate declaration key')
        result[key] = value
    return result


def archive_bytes(archive, filename):
    matches = [entry for entry in archive.infolist() if entry.filename.casefold() == filename.casefold()]
    if len(matches) != 1:
        return None
    entry = matches[0]
    if (entry.filename != filename or entry.is_dir() or entry.file_size > MAX_DECLARATION_BYTES
            or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16)):
        return None
    with archive.open(entry) as stream:
        raw = stream.read(MAX_DECLARATION_BYTES + 1)
    return raw if len(raw) <= MAX_DECLARATION_BYTES else None


def archive_json(archive, filename):
    raw = archive_bytes(archive, filename)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object)
        return value if isinstance(value, dict) else None
    except (UnicodeError, ValueError, RecursionError):
        return None


def archive_name(archive, kind, entrypoint):
    if kind == 'skill':
        entry = entrypoint or 'SKILL.md'
        if PurePosixPath(entry).name != 'SKILL.md':
            return '', ''
        raw = archive_bytes(archive, entry)
        return (skill_name(raw), entry) if raw is not None else ('', '')
    if kind == 'mcp':
        declaration = archive_json(archive, '.mcp.json')
        servers = declaration.get('mcpServers') if declaration else None
        if isinstance(servers, dict) and len(servers) == 1:
            name, configuration = next(iter(servers.items()))
            if isinstance(configuration, dict):
                return identifier(name), '.mcp.json'
        return '', ''
    extension = archive_json(archive, 'extension.json')
    if extension and identifier(extension.get('id')):
        return extension['id'], 'extension.json'
    plugin = archive_json(archive, '.claude-plugin/plugin.json')
    return (identifier(plugin.get('name')), '.claude-plugin/plugin.json') if plugin else ('', '')


def inspect_installation_name(path, tool_type, entrypoint=''):
    """Return declaration evidence only, without installing or changing files."""
    kind = {'Skill': 'skill', 'MCP/Tool': 'mcp', '플러그인/하네스': 'plugin'}.get(tool_type)
    if not kind:
        return None
    path = Path(path)
    try:
        if path.suffix.lower() == '.md' and kind == 'skill':
            with path.open('rb') as stream:
                name = skill_name(stream.read(MAX_DECLARATION_BYTES + 1))
            source = path.name
        elif path.suffix.lower() in {'.zip', '.axextension'}:
            with zipfile.ZipFile(path) as archive:
                name, source = archive_name(archive, kind, entrypoint)
        else:
            return None
    except (OSError, UnicodeError, ValueError, RecursionError, zipfile.BadZipFile, RuntimeError, zlib.error):
        return None
    return dict(kind=kind, label=LABELS[kind], name=name, source=source) if name else None


def name_report(path, tool_type, entrypoint=''):
    identity = inspect_installation_name(path, tool_type, entrypoint)
    return {
        'installationName': identity,
        'installationNameNotice': '' if identity else
            '파일에서 설치 이름을 확인하지 못했습니다. 원본 선언을 확인하고 설치 안내에 실제 사용할 이름을 적어 주세요.',
    }
