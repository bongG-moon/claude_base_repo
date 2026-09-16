"""Bounded skill metadata discovery and opt-in Company Agent preferences.

The registry never edits a skill, changes Claude's native load order, executes
frontmatter, or treats an equal description as proof of a duplicate. Preferences
select the candidate Company Agent recommends; Claude still owns invocation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any
import uuid

from .state_compatibility import check_state_compatibility


SOURCES = ("user", "project", "personal", "company", "plugin", "corporate")
MAX_SKILLS = 512
MAX_ENTRIES = 1024
MAX_JSON_BYTES = 1_048_576
MAX_SKILL_BYTES = 262_144
MAX_PATH_CHARS = 2048
MAX_NAME_CHARS = 128
MAX_WARNINGS = 100
NAME = re.compile(r"^[\w][\w.-]{0,127}$", re.UNICODE)
ID = re.compile(r"^(?:user|project|personal|company|plugin|corporate):[a-f0-9]{24}$")


def _path(value: Path | str, *, absolute_required: bool = False) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or len(raw) > MAX_PATH_CHARS or "\x00" in raw:
        raise ValueError("Skill paths must be bounded, nonempty paths.")
    path = Path(raw).expanduser()
    if ".." in path.parts or (absolute_required and not path.is_absolute()):
        raise ValueError("Skill paths must not contain traversal or relative installation paths.")
    path = path.absolute()
    if len(str(path)) > MAX_PATH_CHARS:
        raise ValueError("Skill path is too long.")
    return path


def _canonical(value: Path | str) -> str:
    return os.path.normcase(str(_path(value)))


def _no_reparse(path: Path) -> None:
    for item in [*reversed(path.parents), path]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError(f"Symlink, junction, or reparse path skipped: {item}")


def _warn(warnings: list[str], message: str) -> None:
    if len(warnings) < MAX_WARNINGS:
        warnings.append(" ".join(message.replace("\x00", " ").split())[:600])


def _read(path: Path, maximum: int) -> bytes | None:
    _no_reparse(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
        raise ValueError(f"Not a bounded regular metadata file: {path}")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError(f"Metadata exceeds the read limit: {path}")
    return raw


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not accepted.")
        result[key] = value
    return result


def _json_read(path: Path) -> dict[str, Any] | None:
    raw = _read(path, MAX_JSON_BYTES)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"Invalid JSON metadata: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON metadata must be an object: {path}")
    return value


def _optional_json(path: Path, warnings: list[str]) -> dict[str, Any]:
    try:
        return _json_read(path) or {}
    except (OSError, ValueError) as exc:
        _warn(warnings, str(exc))
        return {}


def _name(value: Any) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("Skill names must be 1-128 letters, digits, underscores, dots, or hyphens, beginning with a letter, digit, or underscore.")
    return value.casefold()


def _source_order(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or item not in SOURCES for item in value) or len(set(value)) != len(value):
        raise ValueError(f"sourceOrder must be a list of distinct sources: {', '.join(SOURCES)}")
    return value


def _empty_preferences() -> dict[str, Any]:
    return {"schemaVersion": 1, "defaults": {"sourceOrder": [], "skills": {}}, "projects": {}}


def _validate_preferences(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {"schemaVersion", "defaults", "projects"} or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("Unsupported skill preference schema; existing preferences were not reset.")
    projects = value["projects"]
    if not isinstance(projects, dict) or len(projects) > MAX_ENTRIES:
        raise ValueError("Invalid project skill preference map.")
    scopes = [(None, value["defaults"]), *projects.items()]
    for key, scope in scopes:
        allowed = {"sourceOrder", "skills"} if key is None else {"projectRoot", "sourceOrder", "skills"}
        required = {"sourceOrder", "skills"} if key is None else {"projectRoot", "skills"}
        if not isinstance(scope, dict) or not required.issubset(scope) or not set(scope).issubset(allowed):
            raise ValueError("Invalid skill preference scope.")
        _source_order(scope.get("sourceOrder", []))
        skills = scope["skills"]
        if not isinstance(skills, dict) or len(skills) > MAX_ENTRIES:
            raise ValueError("Invalid skill preference choices.")
        for name, candidate_id in skills.items():
            if _name(name) != name or not isinstance(candidate_id, str) or not ID.fullmatch(candidate_id):
                raise ValueError("Invalid skill preference name or candidate ID.")
        if key is not None:
            if not isinstance(scope["projectRoot"], str):
                raise ValueError("Project preference roots must be paths.")
            project = _path(scope["projectRoot"], absolute_required=True)
            if project == Path(project.anchor) or _canonical(project) != key:
                raise ValueError("Project preference keys must match their normalized projectRoot.")
    return value


def _preferences(state_root: Path) -> tuple[Path, dict[str, Any]]:
    state = _path(state_root)
    _no_reparse(state)
    check_state_compatibility(state)
    file = state / "config" / "skill-preferences.json"
    value = _json_read(file)
    return file, _empty_preferences() if value is None else _validate_preferences(value)


def _effective(preferences: dict[str, Any], project: Path | None) -> dict[str, Any]:
    result = {"scope": "defaults", "sourceOrder": list(preferences["defaults"]["sourceOrder"]),
              "skills": dict(preferences["defaults"]["skills"])}
    if project is None:
        return result
    matches = [(len(Path(key).parts), key, scope) for key, scope in preferences["projects"].items()
               if Path(_canonical(project)).is_relative_to(Path(key))]
    if matches:
        _, key, scope = max(matches, key=lambda item: item[0])
        result["scope"] = key
        result["skills"].update(scope["skills"])
        if "sourceOrder" in scope:
            result["sourceOrder"] = list(scope["sourceOrder"])
    return result


def _project_directories(project: Path | None, claude_root: Path, warnings: list[str]) -> list[Path]:
    if project is None:
        return []
    try:
        _no_reparse(project)
        if not project.is_dir():
            _warn(warnings, f"Project directory does not exist: {project}")
            return []
        lineage = []
        home_key = _canonical(Path.home())
        config_key = _canonical(claude_root)
        for directory in [project, *list(project.parents)[:31]]:
            # Global configuration is not evidence that a home directory,
            # profile root, or whole drive is the current business project.
            if (directory == Path(directory.anchor) or _canonical(directory) in {home_key, config_key}
                    or _canonical(directory / ".claude") == config_key):
                break
            lineage.append(directory)
        if not lineage:
            return []
        for index, directory in enumerate(lineage):
            marker = directory / ".git"
            # The marker's contents are never followed (worktrees use a file).
            if marker.exists() or marker.is_symlink():
                return lineage[:index + 1]
        for index, directory in enumerate(lineage):
            marker = directory / ".claude"
            try:
                _no_reparse(marker)
            except (OSError, ValueError) as exc:
                _warn(warnings, str(exc))
                break
            if marker.is_dir():
                # No Git marker: the nearest actual local configuration root
                # provides a bounded parent for nested business-project CWDs.
                return lineage[:index + 1]
        return [project]
    except (OSError, ValueError) as exc:
        _warn(warnings, str(exc))
        return []


def _scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, str) else ""
        except ValueError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value.split(" #", 1)[0].strip()


def _frontmatter_field(raw: bytes, name: str) -> str:
    """Read one top-level scalar without parsing other plugins' YAML dialects."""
    lines = raw.decode('utf-8-sig').splitlines()
    if not lines or lines[0].strip() != '---':
        return ''
    value = ''
    for line in lines[1:]:
        if line.strip() == '---':
            break
        match = re.match(r'^' + re.escape(name) + r':\s*(.*)$', line)
        if match:
            value = _scalar(match.group(1))
    return value


def _metadata(raw: bytes, fallback: str) -> tuple[str, str, bool]:
    text = raw.decode("utf-8-sig")
    lines = text[:16_384].splitlines()
    fields: dict[str, str] = {}
    if lines and lines[0].strip() == "---":
        closing = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
        if closing is not None:
            active: str | None = None
            for line in lines[1:closing]:
                if line[:1].isspace() and active == "description":
                    fields["description"] += " " + line.strip()
                    continue
                active = None
                match = re.match(r"^(name|description):\s*(.*)$", line)
                if match:
                    key, value = match.groups()
                    if key not in fields:
                        fields[key] = "" if value in {">", "|", ">-", "|-", ">+", "|+"} else _scalar(value)
                        active = key
    invalid_name = False
    name = fields.get("name", fallback)
    try:
        _name(name)
    except ValueError:
        name, invalid_name = fallback, True
        _name(name)
    description = " ".join(fields.get("description", "").replace("\x00", " ").split())[:600]
    return name, description, invalid_name


def _manifest(plugin: Path, warnings: list[str]) -> dict[str, Any]:
    return _optional_json(plugin / ".claude-plugin" / "plugin.json", warnings)


def _plugin_name(plugin: Path, manifest: dict[str, Any]) -> str:
    name = manifest.get("name", plugin.name)
    _name(name)
    return name.casefold()


def _plugin_skill_roots(plugin: Path, manifest: dict[str, Any], warnings: list[str]) -> list[Path]:
    roots = [plugin / "skills"]
    extra = manifest.get("skills", [])
    if isinstance(extra, str):
        extra = [extra]
    if not isinstance(extra, list) or len(extra) > 32:
        _warn(warnings, f"Invalid or oversized plugin skills declaration: {plugin}")
        return roots
    for relative in extra:
        try:
            if not isinstance(relative, str) or not relative or len(relative) > MAX_PATH_CHARS or "\\" in relative or ":" in relative:
                raise ValueError("Invalid relative plugin skill path.")
            part = Path(relative)
            if part.is_absolute() or ".." in part.parts:
                raise ValueError("Plugin skill path traversal skipped.")
            target = _path(plugin / part)
            if not target.is_relative_to(plugin):
                raise ValueError("Plugin skill path escaped the plugin.")
            _no_reparse(target)
            roots.append(target)
        except (OSError, ValueError) as exc:
            _warn(warnings, f"{exc} Plugin: {plugin}")
    return list(dict.fromkeys(roots))


def _installed_plugins(claude: Path, project: Path | None, lineage: list[Path], warnings: list[str]) -> list[tuple[str, Path]]:
    enabled: dict[str, bool] = {}
    settings = [claude / "settings.json"]
    for directory in reversed(lineage):
        settings.extend((directory / ".claude" / "settings.json", directory / ".claude" / "settings.local.json"))
    for file in settings:
        overlay = _optional_json(file, warnings).get("enabledPlugins", {})
        if not isinstance(overlay, dict) or len(overlay) > MAX_ENTRIES:
            _warn(warnings, f"Invalid enabledPlugins settings: {file}")
            continue
        for key, flag in overlay.items():
            if isinstance(key, str) and len(key) <= 256 and type(flag) is bool:
                enabled[key] = flag
    registry = _optional_json(claude / "plugins" / "installed_plugins.json", warnings)
    plugins = registry.get("plugins", {})
    if not isinstance(plugins, dict) or len(plugins) > MAX_ENTRIES:
        _warn(warnings, "Invalid or oversized installed plugin inventory.")
        return []
    result = []
    for plugin_id, records in sorted(plugins.items()):
        if not isinstance(plugin_id, str) or len(plugin_id) > 256 or enabled.get(plugin_id) is not True:
            continue
        if not isinstance(records, list) or len(records) > MAX_ENTRIES:
            _warn(warnings, f"Invalid installation records for plugin: {plugin_id}")
            continue
        eligible = []
        for record in records:
            if not isinstance(record, dict):
                _warn(warnings, f"Invalid installation entry for plugin: {plugin_id}")
                continue
            scope = record.get("scope")
            if not isinstance(scope, str):
                _warn(warnings, f"Invalid installation scope for plugin: {plugin_id}")
                continue
            rank = 0
            try:
                if scope in {"project", "local"}:
                    if project is None or not isinstance(record.get("projectPath"), str):
                        continue
                    target = _path(record["projectPath"], absolute_required=True)
                    _no_reparse(target)
                    if not Path(_canonical(project)).is_relative_to(Path(_canonical(target))):
                        continue
                    rank = len(target.parts) * 2 + (scope == "local")
                elif scope != "user":
                    continue
                if not isinstance(record.get("installPath"), str):
                    raise ValueError("Installed plugin has no absolute installPath.")
                path = _path(record["installPath"], absolute_required=True)
                _no_reparse(path)
                eligible.append((rank, path))
            except (OSError, ValueError) as exc:
                _warn(warnings, str(exc))
        if eligible:
            # Native project installations override the user installation of
            # the same plugin ID. Inventory order breaks equal-scope ties.
            result.append((plugin_id, max(enumerate(eligible), key=lambda item: (item[1][0], item[0]))[1][1]))
    return result


def _resolution(name: str, candidates: list[dict[str, Any]], effective: dict[str, Any]) -> dict[str, Any]:
    chosen = effective["skills"].get(name)
    if chosen:
        if any(item["id"] == chosen for item in candidates):
            return {"status": "selected", "selectedId": chosen, "reason": "Explicit skill preference."}
        return {"status": "stale-choice", "selectedId": chosen, "reason": "The saved candidate is unavailable; no replacement was selected."}
    if not candidates:
        return {"status": "not-found", "reason": "No matching available skill."}
    if len(candidates) == 1:
        return {"status": "available", "selectedId": candidates[0]["id"], "reason": "One available candidate."}
    order = effective["sourceOrder"]
    for source in order:
        matches = [item for item in candidates if item["source"] == source]
        if len(matches) == 1:
            return {"status": "selected", "selectedId": matches[0]["id"], "reason": "User-configured source order."}
        if len(matches) > 1:
            return {"status": "unresolved", "reason": "Several candidates share the highest configured source; choose a candidate ID."}
    return {"status": "unresolved", "reason": "No explicit preference distinguishes these candidates."}


def inventory_skills(state_root: Path, *, project_root: Path | None = None,
                     claude_root: Path | None = None, plugin_root: Path | None = None,
                     incoming_plugin: Path | None = None, incoming_skill: Path | None = None,
                     knowledge_root: Path | None = None, metadata_cache: bool = False) -> dict[str, Any]:
    """Read known skill locations; optional runtime-only disposable metadata cache."""
    preference_file, preferences = _preferences(state_root)
    state = _path(state_root)
    project = _path(project_root) if project_root is not None else None
    claude = _path(claude_root or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    warnings: list[str] = []
    lineage = _project_directories(project, claude, warnings)
    effective = _effective(preferences, project)
    candidates: dict[str, dict[str, Any]] = {}
    seen_paths: set[tuple[str, bool]] = set()
    cache = None
    if metadata_cache and not incoming_plugin and not incoming_skill:
        from .skill_metadata_cache import SkillMetadataCache
        cache = SkillMetadataCache(state)

    def add_file(file: Path, source: str, origin: str, logical_root: Path, namespace: str | None, incoming: bool) -> None:
        if len(candidates) >= MAX_SKILLS:
            _warn(warnings, f"Skill inventory is limited to {MAX_SKILLS} candidates.")
            return
        try:
            file = _path(file)
            key = (_canonical(file), incoming)
            if key in seen_paths:
                return
            seen_paths.add(key)
            if cache is not None:
                metadata = cache.metadata(file)
                if metadata is None:
                    return
                name, description, invalid = metadata['name'], metadata['description'], metadata['invalid']
                body_hash, explicit_only = metadata['sha256'], metadata['explicitOnly']
            else:
                raw = _read(file, MAX_SKILL_BYTES)
                if raw is None:
                    return
                name, description, invalid = _metadata(raw, file.parent.name)
                body_hash = hashlib.sha256(raw).hexdigest()
                explicit_only = _frontmatter_field(raw, 'disable-model-invocation').casefold() == 'true'
            if invalid:
                _warn(warnings, f"Invalid declared skill name; using its folder name: {file}")
            relative = file.relative_to(logical_root).as_posix().casefold()
            digest = hashlib.sha256(f"{source}\0{origin}\0{relative}".encode("utf-8")).hexdigest()[:24]
            candidate_id = f"{source}:{digest}"
            invocation = f"{namespace}:{name}" if namespace else (name if source in {"user", "project"} else "")
            candidate = {"id": candidate_id, "name": name, "source": source, "origin": origin,
                         "path": str(file), "description": description,
                         "invocation": invocation,
                         "sha256": body_hash, "incoming": incoming,
                         "explicitOnly": explicit_only}
            if candidate_id not in candidates or incoming:
                candidates[candidate_id] = candidate
        except (OSError, ValueError, UnicodeError) as exc:
            _warn(warnings, f"Skill metadata skipped: {file}. {exc}")

    def scan(root: Path, source: str, origin: str, logical_root: Path | None = None,
             namespace: str | None = None, incoming: bool = False) -> None:
        try:
            root = _path(root)
            _no_reparse(root)
            if not root.exists():
                return
            logical = logical_root or root
            if root.is_file():
                if root.name == "SKILL.md":
                    add_file(root, source, origin, logical, namespace, incoming)
                return
            if (root / "SKILL.md").exists():
                add_file(root / "SKILL.md", source, origin, logical, namespace, incoming)
                return
            # Claude skill roots contain immediate skill directories. Never
            # crawl their scripts, references, or arbitrary project contents.
            entries = []
            with os.scandir(root) as stream:
                for entry in stream:
                    entries.append(entry.name)
                    if len(entries) > MAX_ENTRIES:
                        _warn(warnings, f"Skill directory entry limit reached: {root}")
                        break
            for entry in sorted(entries[:MAX_ENTRIES], key=str.casefold):
                directory = root / entry
                try:
                    _no_reparse(directory)
                    if directory.is_dir():
                        add_file(directory / "SKILL.md", source, origin, logical, namespace, incoming)
                except (OSError, ValueError) as exc:
                    _warn(warnings, str(exc))
        except (OSError, ValueError) as exc:
            _warn(warnings, str(exc))

    scan(claude / "skills", "user", _canonical(claude))
    for directory in reversed(lineage):
        scan(directory / ".claude" / "skills", "project", _canonical(directory))
    personal = state / "personal-root" / ".claude" / "skills"
    scan(personal, "personal", _canonical(state))
    if knowledge_root is not None:
        corporate = _path(knowledge_root)
        scan(corporate / ".claude" / "skills", "corporate", _canonical(corporate))

    active: tuple[Path, dict[str, Any], str] | None = None
    incoming: tuple[Path, dict[str, Any], str] | None = None
    for value, is_incoming in ((plugin_root, False), (incoming_plugin, True)):
        if value is None:
            continue
        try:
            path = _path(value)
            _no_reparse(path)
            manifest = _manifest(path, warnings)
            item = (path, manifest, _plugin_name(path, manifest))
            if is_incoming:
                incoming = item
            else:
                active = item
        except (OSError, ValueError) as exc:
            _warn(warnings, str(exc))
    company_name = active[2] if active else "company-agent"
    installed = []
    for plugin_id, path in _installed_plugins(claude, project, lineage, warnings):
        try:
            manifest = _manifest(path, warnings)
            installed.append((plugin_id, path, manifest, _plugin_name(path, {"name": plugin_id.split("@", 1)[0], **manifest})))
        except ValueError as exc:
            _warn(warnings, str(exc))
    incoming_installed_ids = [item[0] for item in installed if incoming and item[3] == incoming[2]]
    for plugin_id, path, manifest, name in installed:
        # An explicitly active/new company version is one logical plugin, not
        # an extra competing installation. Version paths never enter its ID.
        if name == company_name and (active or (incoming and incoming[2] == company_name)):
            continue
        if incoming and name == incoming[2] and len(incoming_installed_ids) == 1:
            continue
        for root in _plugin_skill_roots(path, manifest, warnings):
            scan(root, "plugin", plugin_id.casefold(), path, name)
    for item, is_incoming in ((active, False), (incoming, True)):
        if item is None:
            continue
        path, manifest, name = item
        if not is_incoming and incoming and incoming[2] == name:
            continue
        source = "company" if not is_incoming or name == company_name else "plugin"
        origin = name if source == "company" else (incoming_installed_ids[0].casefold() if len(incoming_installed_ids) == 1 else name)
        for root in _plugin_skill_roots(path, manifest, warnings):
            scan(root, source, origin, path, name, is_incoming)
    if incoming_skill is not None:
        # A standalone incoming skill previews installation in personal state.
        # Use its destination-relative folder, not its temporary staging path.
        path = _path(incoming_skill)
        directory = path.parent if path.name == "SKILL.md" else path
        file = directory / "SKILL.md"
        scan(file, "personal", _canonical(state), directory.parent, incoming=True)

    skills = sorted(candidates.values(), key=lambda item: (_name(item["name"]), item["source"], item["origin"], item["id"]))
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in skills:
        groups[_name(candidate["name"])].append(candidate)
    conflicts = []
    for name, group in sorted(groups.items()):
        if len(group) < 2:
            continue
        plain = [item for item in group if item["source"] in {"user", "project"} and item["invocation"] and ":" not in item["invocation"]]
        kind = "native-name-collision" if len(plain) > 1 else ("namespaced-overlap" if any(":" in item["invocation"] for item in group) else "workflow-name-overlap")
        conflicts.append({"name": name, "kind": kind,
                          "candidates": group, "resolution": _resolution(name, group, effective)})
    complete = not warnings
    if cache is not None and complete:
        cache.save()
    for name, candidate_id in effective["skills"].items():
        if not any(item["id"] == candidate_id for item in groups.get(name, [])):
            _warn(warnings, f"Stale skill preference for {name}: {candidate_id}; no replacement selected.")
    source_counts: dict[str, int] = {}
    plugin_counts: dict[str, int] = {}
    for item in skills:
        source_counts[item["source"]] = source_counts.get(item["source"], 0) + 1
        if item["source"] == "plugin":
            plugin_counts[item["origin"]] = plugin_counts.get(item["origin"], 0) + 1
    return {"skills": skills, "conflicts": conflicts, "warnings": warnings, "complete": complete,
            "summary": {"total": len(skills), "bySource": source_counts, "byPlugin": plugin_counts},
            "preferencesPath": str(preference_file), "preferences": preferences, "effectivePreferences": effective,
            "note": "Exact names only; descriptions do not prove semantic duplication. Preferences guide Company Agent recommendations and do not change native Claude precedence. Personal and corporate candidates require reading the selected SKILL.md; they are not registered native invocations."}


def resolve_skill(state_root: Path, name: str, **inventory_options: Any) -> dict[str, Any]:
    normalized = _name(name)
    inventory = inventory_skills(state_root, **inventory_options)
    candidates = [item for item in inventory["skills"] if _name(item["name"]) == normalized]
    return {"name": normalized, "candidates": candidates,
            "resolution": _resolution(normalized, candidates, inventory["effectivePreferences"]),
            "warnings": inventory["warnings"], "complete": inventory["complete"], "preferencesPath": inventory["preferencesPath"]}


def search_skills(state_root: Path, query: str = "", *, limit: int = 50, include_inventory: bool = False,
                  **inventory_options: Any) -> dict[str, Any]:
    if not isinstance(query, str) or len(query) > 2000 or type(limit) is not int or not 1 <= limit <= MAX_SKILLS:
        raise ValueError(f"Search requires a query up to 2000 characters and a limit from 1 to {MAX_SKILLS}.")
    inventory = inventory_skills(state_root, **inventory_options)
    tokens = query.casefold().split()[:32]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in inventory["skills"]:
        groups[_name(item["name"])].append(item)
    available = []
    for name, candidates in groups.items():
        resolution = _resolution(name, candidates, inventory["effectivePreferences"])
        if resolution["status"] in {"selected", "available"}:
            available.extend(item for item in candidates if item["id"] == resolution["selectedId"])
    def score(item: dict[str, Any]) -> int:
        text = " ".join((item["name"], item["description"], item["source"], item["invocation"])).casefold()
        title = f'{item["name"]} {item["invocation"]}'.casefold()
        return sum(1 + 2 * (token in title) for token in tokens if token in text)
    matching = [item for item in available if not tokens or score(item) > 0]
    matching.sort(key=lambda item: (-score(item), _name(item["name"]), item["id"]))
    result = {"query": query, "skills": matching[:limit], "total": len(matching),
            "conflicts": [item for item in inventory["conflicts"] if not tokens or any(score(candidate) > 0 for candidate in item["candidates"])],
            "warnings": inventory["warnings"], "complete": inventory["complete"], "preferencesPath": inventory["preferencesPath"]}
    if include_inventory:
        result["inventory"] = inventory
    return result


def _scope(preferences: dict[str, Any], project_root: Path | None, *, create: bool = True) -> tuple[str, dict[str, Any] | None]:
    if project_root is None:
        return "defaults", preferences["defaults"]
    project = _path(project_root, absolute_required=True)
    _no_reparse(project)
    if project == Path(project.anchor) or not project.is_dir():
        raise ValueError("Project preference scope requires an existing project directory, not a drive root.")
    key = _canonical(project)
    if create and key not in preferences["projects"]:
        preferences["projects"][key] = {"projectRoot": str(project), "skills": {}}
    return key, preferences["projects"].get(key)


def _write_preferences(state_root: Path, file: Path, before: dict[str, Any], after: dict[str, Any]) -> None:
    _validate_preferences(after)
    if before == after:
        return
    state = _path(state_root)
    _no_reparse(state)
    _no_reparse(file)
    check_state_compatibility(state)
    raw = _read(file, MAX_JSON_BYTES)
    if raw is None:
        if before != _empty_preferences():
            raise ValueError("Skill preferences changed during this operation; retry.")
    elif _json_read(file) != before:
        raise ValueError("Skill preferences changed during this operation; retry.")
    history = file.parent / "skill-preferences-history"
    _no_reparse(history)
    content = (json.dumps(after, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(content) > MAX_JSON_BYTES:
        raise ValueError("Skill preferences exceed the supported size; existing preferences were preserved.")
    file.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        history.mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = history / f"{timestamp}-{uuid.uuid4().hex}.json"
        with backup.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    descriptor, temporary = tempfile.mkstemp(prefix=".skill-preferences-", suffix=".tmp", dir=file.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _no_reparse(file)
        if _read(file, MAX_JSON_BYTES) != raw:
            raise ValueError("Skill preferences changed during this operation; retry.")
        os.replace(temporary, file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def set_skill_preference(state_root: Path, name: str, candidate_id: str, *, project_root: Path | None = None,
                         **inventory_options: Any) -> dict[str, Any]:
    normalized = _name(name)
    if not isinstance(candidate_id, str) or not ID.fullmatch(candidate_id):
        raise ValueError("Select a candidate ID returned by the skill inventory.")
    result = resolve_skill(state_root, name, project_root=project_root, **inventory_options)
    if not any(item["id"] == candidate_id for item in result["candidates"]):
        raise ValueError("The selected candidate does not exist for this skill in the requested scope.")
    file, before = _preferences(state_root)
    after = json.loads(json.dumps(before))
    scope_name, scope = _scope(after, project_root)
    assert scope is not None
    scope["skills"][normalized] = candidate_id
    _write_preferences(state_root, file, before, after)
    return {"ok": True, "scope": scope_name, "name": normalized, "selectedId": candidate_id,
            "preferencesPath": str(file), "resolution": {"status": "selected", "selectedId": candidate_id, "reason": "Explicit skill preference."}}


def set_skill_source_order(state_root: Path, order: list[str], *, project_root: Path | None = None) -> dict[str, Any]:
    _source_order(order)
    file, before = _preferences(state_root)
    after = json.loads(json.dumps(before))
    scope_name, scope = _scope(after, project_root)
    assert scope is not None
    scope["sourceOrder"] = list(order)
    _write_preferences(state_root, file, before, after)
    return {"ok": True, "scope": scope_name, "sourceOrder": order, "preferencesPath": str(file)}


def reset_skill_preferences(state_root: Path, *, project_root: Path | None = None, name: str | None = None) -> dict[str, Any]:
    normalized = _name(name) if name is not None else None
    file, before = _preferences(state_root)
    after = json.loads(json.dumps(before))
    scope_name, scope = _scope(after, project_root, create=False)
    if scope is not None:
        if normalized is not None:
            scope["skills"].pop(normalized, None)
        elif project_root is None:
            after["defaults"] = {"sourceOrder": [], "skills": {}}
        else:
            del after["projects"][scope_name]
    _write_preferences(state_root, file, before, after)
    return {"ok": True, "scope": scope_name, "preferencesPath": str(file)}
