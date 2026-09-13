"""Offline lab support. Standard library only; never writes Claude configuration."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile


def safe(path: Path) -> Path:
    """Reject links/junctions on all existing ancestors, including missing children."""
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("링크/연결 폴더는 연습 대상으로 사용할 수 없습니다: " + str(item))
    return path


def read_json(path: Path) -> dict:
    return json.loads(safe(path).read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with safe(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_check(root: Path, meta: dict) -> dict:
    archive = safe(root / "installer" / meta["bundleName"])
    if sha(archive) != meta["bundleSha256"]:
        return {"ok": False, "message": "설치 압축파일이 원본과 다릅니다. 설치하지 마세요."}
    errors = []
    target = safe(root / "installer" / "package")
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            rel = Path(entry.filename.replace("\\", "/"))
            if rel.is_absolute() or ".." in rel.parts or ":" in str(rel):
                raise ValueError("잘못된 압축파일 경로")
            if entry.is_dir():
                continue
            path = safe(target / rel)
            if not path.is_file() or sha(path) != hashlib.sha256(bundle.read(entry)).hexdigest():
                errors.append(entry.filename)
    return {"ok": not errors, "differentFiles": errors,
            "message": "설치파일 원본과 일치" if not errors else "풀어놓은 설치파일이 달라졌습니다. 설치 중단"}


def registration_check(root: Path, meta: dict, local_app_data: Path | None = None,
                       config_root: Path | None = None) -> dict:
    workspace = safe(root / "workspace")
    state = safe(root / "personal-state")
    local = local_app_data or Path(os.environ.get("LOCALAPPDATA", ""))
    project_hash = hashlib.sha256(str(workspace).upper().encode("utf-8")).hexdigest()[:16]
    record_file = local / "CompanyAgent" / "installations" / "projects" / project_hash / "company-agent-install.json"
    if not safe(record_file).is_file():
        return {"ready": False, "code": "not_installed", "message": "테스트 프로젝트 설치가 필요합니다."}
    record = read_json(record_file)
    active_config = config_root or Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    conditions = {
        "project": record.get("scope") == "Project" and record.get("nativeClaudeScope") == "local"
            and safe(Path(record.get("projectRoot", "."))) == workspace,
        "isolatedState": safe(Path(record.get("userStateRoot", "."))) == state,
        "version": record.get("coreVersion") == meta["coreVersion"],
        "profile": safe(Path(record.get("claudeConfigRoot", "."))) == safe(active_config),
        "schema": record.get("schemaVersion") == 1 and record.get("enabled") is not False,
        "configOverride": record.get("claudeConfigDirOverride", False) == bool(os.environ.get("CLAUDE_CONFIG_DIR")),
    }
    config = safe(active_config)
    settings_file = workspace / ".claude" / "settings.local.json"
    inventory_file = config / "plugins" / "installed_plugins.json"
    plugin_id = "company-agent@company-agent-local"
    conditions["enabled"] = settings_file.is_file() and read_json(settings_file).get("enabledPlugins", {}).get(plugin_id) is True
    inventory = read_json(inventory_file) if inventory_file.is_file() else {}
    matches = [entry for entry in inventory.get("plugins", {}).get(plugin_id, [])
               if entry.get("scope") == "local" and entry.get("projectPath")
               and safe(Path(entry["projectPath"])) == workspace]
    conditions["registered"] = len(matches) == 1 and matches[0].get("version") == meta["coreVersion"]
    if conditions["registered"]:
        install_path = matches[0].get("installPath")
        conditions["pluginFiles"] = bool(install_path) and safe(Path(install_path) / "hooks" / "hooks.json").is_file()
    ready = all(conditions.values())
    return {"ready": ready, "checks": conditions, "record": str(record_file),
            "state": str(state), "version": record.get("coreVersion"),
            "message": "프로젝트 설치 정보 확인됨. T01에서 실제 세션 적용도 확인하세요." if ready
            else "설치 정보가 현재 연습 폴더/개인 상태/버전과 일치하지 않습니다. 자동 변경하지 않았습니다."}


def fixture_check(root: Path) -> dict:
    baseline = read_json(root / "operator" / "baseline.json")
    folder = safe(root / "workspace" / "01-folder-organize")
    baseline_files = baseline["organizer"]
    observed = {}
    for directory, folders, files in os.walk(folder, followlinks=False):
        safe(Path(directory))
        for name in folders:
            safe(Path(directory) / name)
        for name in files:
            file = safe(Path(directory) / name)
            observed[file.relative_to(folder).as_posix()] = sha(file)
    original = all(observed.get(name) == digest for name, digest in baseline_files.items())
    content_equal = Counter(observed.values()) == Counter(baseline_files.values())
    changed = [name for name, digest in baseline_files.items() if observed.get(name) != digest]
    immutable = []
    for name, digest in baseline["inputs"].items():
        path = safe(root / "workspace" / name)
        if not path.is_file() or sha(path) != digest:
            immutable.append(name)
    return {"originalLocations": original, "sameContentsAndCount": content_equal,
            "differentOriginalPaths": changed, "differentInputFiles": immutable,
            "explanation": "원래 위치 일치는 취소/되돌리기 확인용입니다. 이동 후 위치 변경 자체는 정상일 수 있습니다.",
            "notVerified": "이 검사는 Claude 응답, 실제 승인, Memory, 자동 학습, Outlook, DB를 판정하지 않습니다."}


def check(root: Path, installation: bool = True) -> dict:
    root = safe(root)
    meta = read_json(root / "lab.json")
    if meta.get("schemaVersion") != 1 or meta.get("kind") != "company-agent-test-lab":
        raise ValueError("Company Agent 연습 폴더 표시를 확인할 수 없습니다.")
    result = {"python": sys.version.split()[0], "package": package_check(root, meta),
              "fixtures": fixture_check(root), "fixtureEnvironmentReady": True}
    result["fixtureEnvironmentReady"] = result["package"]["ok"] and not result["fixtures"]["differentInputFiles"]
    if installation:
        result["installation"] = registration_check(root, meta)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fixtures-only", action="store_true")
    args = parser.parse_args()
    try:
        result = check(args.root, installation=not args.fixtures_only)
        if args.json:
            print(json.dumps(result, ensure_ascii=True))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["package"]["ok"] else 2
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    raise SystemExit(main())
