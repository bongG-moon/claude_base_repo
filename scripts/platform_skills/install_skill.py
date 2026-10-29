"""Install this verified Skill into an explicitly selected Claude scope (Python 3.11+)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import time

# Merely asking for a scope or running --dry-run must not create __pycache__.
sys.dont_write_bytecode = True
from install_scope import select_scope

LEGACY_PREFIX = "square-company-"
LEGACY_PACKAGE_PREFIX = "company.skills."
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class InstallError(ValueError):
    """An install condition the user can resolve without changing their profile."""


def reject_links(path: Path) -> None:
    """Inspect the original lexical path before resolve() can hide a junction."""
    absolute = Path(os.path.abspath(path))
    for part in [*reversed(absolute.parents), absolute]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise InstallError(f"심볼릭 링크·정션·재분석 지점을 통해 설치하지 않습니다: {part}")


def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise InstallError(f"중복 JSON 항목이 있습니다: {key}")
        result[key] = value
    return result


def read_json(data: bytes):
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InstallError("패키지 JSON 형식을 읽을 수 없습니다.") from error


def safe_relative(raw: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or ":" in raw or "\0" in raw:
        raise InstallError("패키지에 안전하지 않은 파일 경로가 있습니다.")
    parts = raw.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if any(not p or p in {".", ".."} or p[-1:] in {" ", "."}
           or any(c in p for c in '<>"|?*') or any(ord(c) < 32 for c in p)
           or p.split(".", 1)[0].upper() in reserved for p in parts):
        raise InstallError(f"패키지에 안전하지 않은 파일 경로가 있습니다: {raw}")
    value = PurePosixPath(raw)
    if value.is_absolute():
        raise InstallError("패키지는 상대 파일 경로만 사용할 수 있습니다.")
    return value


def verified_package(source: Path):
    reject_links(source)
    if not source.is_dir():
        raise InstallError("압축을 푼 패키지 폴더가 없습니다.")
    manifest_path = source / "PACKAGE_CONTENTS.json"
    reject_links(manifest_path)
    raw_manifest = manifest_path.read_bytes()
    manifest = read_json(raw_manifest)
    records = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(records, dict) or not records:
        raise InstallError("PACKAGE_CONTENTS.json의 files 목록이 올바르지 않습니다.")
    if not {"SKILL.md", "ai-square.json", "INSTALL.md"}.issubset(records):
        raise InstallError("SKILL.md, ai-square.json, INSTALL.md의 검사 정보가 필요합니다.")
    files = {}
    seen = set()
    for name, expected in records.items():
        relative = safe_relative(name)
        folded = name.casefold()
        if folded in seen or folded == "package_contents.json":
            raise InstallError("중복 경로나 자기 자신을 포함하는 검사 목록입니다.")
        seen.add(folded)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise InstallError(f"SHA-256 검사값이 올바르지 않습니다: {name}")
        path = source.joinpath(*relative.parts)
        reject_links(path)
        if not path.is_file():
            raise InstallError(f"필수 파일이 없습니다: {name}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected.lower():
            raise InstallError(f"파일이 배포 당시와 다릅니다. 새 ZIP을 다시 받아 주세요: {name}")
        files[name] = data
    metadata = read_json(files["ai-square.json"])
    package_id = metadata.get("packageId") if isinstance(metadata, dict) else None
    if not isinstance(package_id, str) or not re.fullmatch(r"[a-z][a-z0-9.-]{2,79}", package_id):
        raise InstallError("ai-square.json의 packageId가 올바르지 않습니다.")
    skill = files["SKILL.md"].decode("utf-8-sig")
    frontmatter = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\s|$)", skill, re.S)
    names = re.findall(r"^name:\s*([a-z0-9-]+)\s*$", frontmatter.group(1), re.M) if frontmatter else []
    if len(names) != 1 or len(names[0]) > 64 or not SKILL_NAME.fullmatch(names[0]):
        raise InstallError("SKILL.md의 name은 64자 이하의 영문 소문자·숫자·하이픈 이름이어야 합니다.")
    safe_relative(names[0])  # Also reject Windows reserved device names.
    if package_id.startswith(LEGACY_PACKAGE_PREFIX):
        slug = package_id.removeprefix(LEGACY_PACKAGE_PREFIX)
        if not SKILL_NAME.fullmatch(slug) or names[0] not in {slug, LEGACY_PREFIX + slug}:
            raise InstallError("SKILL.md의 이름이 packageId의 스킬 이름과 다릅니다. 올바른 ZIP을 다시 받아 주세요.")
    elif SKILL_NAME.fullmatch(package_id) and names[0] != package_id:
        raise InstallError("SKILL.md의 이름과 packageId가 다릅니다. 올바른 ZIP을 다시 받아 주세요.")
    # Snapshot verified bytes. Copying does not reopen unverified source paths.
    files["PACKAGE_CONTENTS.json"] = raw_manifest
    return names[0], package_id, files


def reject_related_install(skills_root: Path, name: str, package_id: str) -> None:
    """Check only the old/new sibling name in the explicitly selected scope.

    A name change is not authorization to migrate, overwrite or delete user
    edits. The former company.skills ID and the plain Skill ID identify the
    same package; no profile-wide scan or automatic migration runs.
    """
    related_name = name.removeprefix(LEGACY_PREFIX) if name.startswith(LEGACY_PREFIX) else LEGACY_PREFIX + name
    if not related_name:
        return
    related = skills_root / related_name
    reject_links(related)
    if not os.path.lexists(related):
        return
    metadata_path = related / "ai-square.json"
    reject_links(metadata_path)
    installed_id = None
    try:
        with metadata_path.open("rb") as stream:
            raw = stream.read(65_537)
        if len(raw) <= 65_536:
            metadata = read_json(raw)
            if isinstance(metadata, dict):
                installed_id = metadata.get("packageId")
    except (OSError, ValueError):
        pass
    def identity(value):
        if isinstance(value, str) and value.startswith(LEGACY_PACKAGE_PREFIX):
            slug = value.removeprefix(LEGACY_PACKAGE_PREFIX)
            if SKILL_NAME.fullmatch(slug):
                return slug
        return value

    same_package = identity(installed_id) == identity(package_id)
    if (isinstance(installed_id, str) and re.fullmatch(r"[a-z][a-z0-9.-]{2,79}", installed_id)
            and not same_package):
        return  # A different package is not a known old-name installation.
    reason = ("같은 스킬이 다른 이름으로 이미 설치되어 있습니다" if same_package
              else "이전/새 이름의 폴더가 있지만 설치 정보를 확인할 수 없습니다")
    raise InstallError(f"{reason}: {related}\n중복 설치하지 않았습니다. 기존 내용과 사용자 수정 사항을 확인하고, 유지할 스킬을 정한 뒤 기존 폴더를 skills 밖에 백업·이동하고 다시 실행하세요. 자동 이동·삭제는 하지 않습니다.")


def clean_staging(staging: Path, skills_root: Path, identity) -> None:
    if staging.parent != skills_root or not staging.name.startswith(".square-install-"):
        raise InstallError("임시 경로의 범위가 달라 자동 정리를 중단했습니다.")
    reject_links(staging)
    info = staging.stat()
    if (info.st_dev, info.st_ino) != identity:
        raise InstallError("임시 폴더가 변경되어 자동 정리를 중단했습니다.")
    for path in staging.rglob("*"):
        reject_links(path)
    shutil.rmtree(staging)


def install(source: Path, *, scope=None, project_dir=None, yes=False, dry_run=False,
            interactive=None, ask=input, environ=None):
    interactive = sys.stdin.isatty() if interactive is None else interactive
    # The shared distribution helper is always called before any installation write.
    selection = select_scope(scope, project_dir, interactive=interactive, ask=ask)
    environ = os.environ if environ is None else environ
    selected = selection["scope"]
    if selected == "project":
        lexical_base = Path(project_dir or Path.cwd()).expanduser()
        reject_links(lexical_base)
        config_root = Path(selection["baseDirectory"]) / ".claude"
    else:
        configured = environ.get("CLAUDE_CONFIG_DIR", "")
        if configured:
            config_root = Path(configured).expanduser()
            if not config_root.is_absolute():
                raise InstallError("CLAUDE_CONFIG_DIR는 절대 경로여야 합니다. 설정을 임의로 바꾸지 않습니다.")
        else:
            config_root = Path.home() / ".claude"
    reject_links(config_root)
    skills_root = Path(os.path.abspath(config_root / "skills"))
    reject_links(skills_root)
    source = Path(os.path.abspath(source))
    name, package_id, files = verified_package(source)
    target = skills_root / name
    reject_links(target)
    print(f"설치 범위: {'현재 디렉토리(프로젝트)' if selected == 'project' else '내 계정 전역'}")
    print(f"설치 위치: {target}")
    print(f"패키지: {package_id} / {len(files)}개 파일")
    if os.path.lexists(target):
        raise InstallError(f"이미 설치된 폴더가 있어 덮어쓰지 않습니다: {target}\n기존 폴더를 별도 위치에 직접 백업한 뒤 대상 폴더를 비우지 말고 이동하고 다시 실행하세요.")
    reject_related_install(skills_root, name, package_id)
    if dry_run:
        print("확인만 완료했습니다. 폴더 생성·파일 설치·설정 변경은 하지 않았습니다.")
        return {"status": "dry-run", "scope": selected, "target": str(target), "packageId": package_id}
    if os.name != "nt":
        raise InstallError("이 설치기는 Windows용입니다. 다른 운영체제에서는 --dry-run으로 내용과 경로만 확인할 수 있습니다.")
    if not yes:
        if not interactive:
            raise InstallError("비대화형 설치에는 명시한 --scope와 --yes가 모두 필요합니다.")
        if ask("위 위치에 이 스킬만 설치할까요? [y/N]: ").strip().lower() not in {"y", "yes", "예"}:
            raise InstallError("설치를 취소했습니다. 파일을 변경하지 않았습니다.")
    # Recheck immediately before writes; existing settings and profiles are never edited.
    reject_links(skills_root)
    if os.path.lexists(target):
        raise InstallError("다른 작업이 설치 대상 폴더를 만들었습니다. 기존 폴더를 보존하고 중단합니다.")
    reject_related_install(skills_root, name, package_id)
    skills_root.mkdir(parents=True, exist_ok=True)
    reject_links(skills_root)
    staging = Path(tempfile.mkdtemp(prefix=".square-install-", dir=skills_root))
    created = staging.stat()
    identity = (created.st_dev, created.st_ino)
    try:
        for relative, data in files.items():
            destination = staging.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write(data)
        reject_links(skills_root)
        if os.path.lexists(target):
            raise InstallError("설치 대상이 이미 생겨 중단했습니다. 기존 파일은 덮어쓰지 않았습니다.")
        # Windows may briefly lock newly written files. Retry the same atomic
        # rename only, never copy over a target or alter permissions/settings.
        for attempt in range(3):
            reject_links(skills_root)
            if os.path.lexists(target):
                raise InstallError("설치 대상이 이미 생겨 중단했습니다. 기존 파일은 덮어쓰지 않았습니다.")
            reject_related_install(skills_root, name, package_id)
            try:
                # Windows rename fails if target exists, even an empty folder.
                os.rename(staging, target)
                break
            except PermissionError as error:
                if getattr(error, 'winerror', None) not in {5, 32, 33} or attempt == 2:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        if os.path.lexists(staging):
            clean_staging(staging, skills_root, identity)
    print("설치했습니다. Claude에서 스킬 목록을 다시 확인하세요. 설정·후크·MCP·기억·의존성은 변경하지 않았습니다.")
    return {"status": "installed", "scope": selected, "target": str(target), "packageId": package_id}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("project", "user"))
    parser.add_argument("--project-dir", help="프로젝트 범위의 기준 폴더. 생략하면 현재 디렉토리")
    parser.add_argument("--yes", action="store_true", help="표시한 명시적 설치 범위에 설치를 승인")
    parser.add_argument("--dry-run", action="store_true", help="경로와 무결성만 확인, 파일은 변경하지 않음")
    args = parser.parse_args(argv)
    try:
        install(Path(__file__).parent, scope=args.scope, project_dir=args.project_dir,
                yes=args.yes, dry_run=args.dry_run)
    except (OSError, ValueError, EOFError, KeyboardInterrupt) as error:
        print(f"설치하지 못했습니다: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
