"""Bounded static extraction of the main OOXML workbook's embedded VBA source.

Never invokes Excel, executes VBA, decrypts a project, scans nested documents, or
evaluates p-code. oletools is optional and imported only in a timeout-bound child.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import struct
import subprocess
import sys
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
import zipfile

MAX_CONTAINER = 64 * 1024 * 1024
MAX_UNCOMPRESSED = 128 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024
MAX_VBA = 16 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
MAX_TOTAL_SOURCE = 8 * 1024 * 1024
MAX_WORKER_OUTPUT = 12 * 1024 * 1024
MAX_MODULES = 64
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = {"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
              "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument"}
VBA_REL = "http://schemas.microsoft.com/office/2006/relationships/vbaProject"


class ExtractionError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def outcome(status, message=None, **fields):
    return dict(status=status, message=message, macro_executed=False, modules=[],
                compiled_code_checked=False, nested_documents_scanned=False, **fields)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_member(name):
    if (not isinstance(name, str) or not name or "\x00" in name or "\\" in name or ":" in name
            or name.startswith("/") or any(part in {".", "..", ""} for part in name.rstrip("/").split("/"))):
        raise ExtractionError("malformed", "ZIP 내부 경로가 올바르지 않습니다")
    return name


def target_part(source_part, target):
    if not target or any(ord(char) < 32 for char in target) or "\\" in target:
        raise ExtractionError("malformed", "잘못된 내부 연결 경로입니다")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ExtractionError("malformed", "VBA 연결은 외부 주소가 아닌 내부 part여야 합니다")
    try:
        decoded = unquote(parsed.path, errors="strict")
    except UnicodeError as exc:
        raise ExtractionError("malformed", "내부 연결 경로 인코딩이 잘못되었습니다") from exc
    joined = decoded.lstrip("/") if decoded.startswith("/") else posixpath.join(posixpath.dirname(source_part), decoded)
    resolved = posixpath.normpath(joined)
    return safe_member(resolved)


def read_part(archive, name, max_bytes):
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise ExtractionError("malformed", "연결된 OOXML part가 없습니다") from exc
    if info.flag_bits & 1:
        raise ExtractionError("encrypted_or_non_ooxml", "암호화된 ZIP part는 해독하거나 읽지 않습니다")
    if info.file_size > max_bytes:
        raise ExtractionError("limit_exceeded", "연결된 OOXML part가 추출 크기 한도를 넘습니다")
    with archive.open(info) as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ExtractionError("limit_exceeded", "part의 실제 크기가 추출 한도를 넘습니다")
    return data


def xml_part(archive, name):
    raw = read_part(archive, name, MAX_XML)
    markup = raw.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in markup or b"<!ENTITY" in markup:
        raise ExtractionError("malformed", "DTD/entity가 포함된 XML은 처리하지 않습니다")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ExtractionError("malformed", "OOXML 연결 XML이 손상되었습니다") from exc


def relationships(archive, part):
    root = xml_part(archive, part)
    if root.tag != f"{{{REL_NS}}}Relationships":
        raise ExtractionError("malformed", "OOXML 관계 파일 형식이 잘못되었습니다")
    return list(root.findall(f"{{{REL_NS}}}Relationship"))


def main_vba_part(container):
    """Select only root officeDocument -> workbook -> VBA; no embedded-object scan."""
    if len(container) > MAX_CONTAINER:
        raise ExtractionError("limit_exceeded", "입력 파일이 64 MiB 한도를 넘습니다")
    if container.startswith(OLE_MAGIC):
        raise ExtractionError("encrypted_or_non_ooxml", "일반 OOXML ZIP이 아닙니다. 암호화 Office·구형 OLE 형식 등을 확인하세요. 해독은 하지 않았습니다")
    try:
        archive = zipfile.ZipFile(io.BytesIO(container))
    except zipfile.BadZipFile as exc:
        raise ExtractionError("encrypted_or_non_ooxml", "일반 OOXML ZIP이 아닙니다. 암호화·DRM 여부는 이 결과만으로 확정하지 않습니다") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(info.file_size for info in infos) > MAX_UNCOMPRESSED:
            raise ExtractionError("limit_exceeded", "ZIP 항목 수 또는 전체 해제 크기가 한도를 넘습니다")
        # ZipInfo normalizes Windows backslashes and truncates at NUL. Validate
        # the original central-directory name too, before trusting that cleanup.
        for info in infos:
            safe_member(info.orig_filename)
        names = [safe_member(info.filename) for info in infos]
        if len(set(names)) != len(names) or len({name.casefold() for name in names}) != len(names):
            raise ExtractionError("malformed", "중복되거나 대소문자만 다른 ZIP part가 있습니다")
        roots = [rel for rel in relationships(archive, "_rels/.rels") if rel.get("Type") in OFFICE_REL]
        if len(roots) != 1 or roots[0].get("TargetMode", "Internal") != "Internal":
            raise ExtractionError("malformed", "주 통합문서 연결을 하나로 확인할 수 없습니다")
        workbook = target_part("", roots[0].get("Target"))
        wbroot = xml_part(archive, workbook)
        if wbroot.tag not in {"{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook",
                              "{http://purl.oclc.org/ooxml/spreadsheetml/main}workbook"}:
            raise ExtractionError("malformed", "주 문서가 Excel 통합문서가 아닙니다")
        wbpath = PurePosixPath(workbook)
        relpath = str(wbpath.parent / "_rels" / (wbpath.name + ".rels"))
        if relpath not in names:
            return None, None, workbook
        candidates = [rel for rel in relationships(archive, relpath) if rel.get("Type") == VBA_REL]
        if not candidates:
            return None, None, workbook
        if len(candidates) != 1 or candidates[0].get("TargetMode", "Internal") != "Internal":
            raise ExtractionError("malformed", "주 통합문서의 내부 VBA 연결이 하나가 아닙니다")
        part = target_part(workbook, candidates[0].get("Target"))
        content = read_part(archive, part, MAX_VBA)
        if len(content) < 512 or not content.startswith(OLE_MAGIC):
            raise ExtractionError("malformed", "연결된 VBA part가 올바른 OLE 컨테이너가 아닙니다")
        return part, content, workbook


def decompressed_size(data, limit=MAX_SOURCE):
    """Validate MS-OVBA chunk/token bounds without allocating decoded source."""
    if not data or data[0] != 1:
        raise ExtractionError("malformed", "VBA 압축 스트림 서명이 잘못되었습니다")
    cursor, total = 1, 0
    while cursor < len(data):
        if cursor + 2 > len(data):
            raise ExtractionError("malformed", "VBA 압축 헤더가 잘렸습니다")
        header = struct.unpack_from("<H", data, cursor)[0]
        size = (header & 0xFFF) + 3
        end, compressed = cursor + size, bool(header & 0x8000)
        if ((header >> 12) & 7) != 3 or end > len(data) or not compressed and size != 4098:
            raise ExtractionError("malformed", "VBA 압축 chunk가 잘못되었습니다")
        cursor += 2
        produced = 0
        if not compressed:
            produced, cursor = 4096, end
        else:
            while cursor < end:
                flags = data[cursor]
                cursor += 1
                for bit in range(8):
                    if cursor >= end:
                        break
                    if flags & (1 << bit):
                        if cursor + 2 > end or produced == 0:
                            raise ExtractionError("malformed", "VBA copy token이 잘못되었습니다")
                        token = struct.unpack_from("<H", data, cursor)[0]
                        bits = max(4, (produced - 1).bit_length())
                        length = (token & (0xFFFF >> bits)) + 3
                        offset = (token >> (16 - bits)) + 1
                        if offset > produced:
                            raise ExtractionError("malformed", "VBA copy token이 이전 chunk를 참조합니다")
                        produced += length
                        cursor += 2
                    else:
                        produced += 1
                        cursor += 1
                    if produced > 4096:
                        raise ExtractionError("malformed", "VBA 압축 chunk 해제 크기가 4096바이트를 넘습니다")
        total += produced
        if total > limit:
            raise ExtractionError("limit_exceeded", "VBA 원문 해제 크기가 한도를 넘습니다")
    return total


def module_path(index, name, extension):
    slug = re.sub(r"[^\w-]+", "_", str(name), flags=re.UNICODE).strip("_")[:64] or "unnamed"
    ext = "cls" if extension in {"cls", "frm"} else "bas"
    return f"modules/{index:03d}_{slug}.{ext}"


def check_ole_header(data):
    if len(data) < 512 or not data.startswith(OLE_MAGIC):
        raise ExtractionError("malformed", "OLE 헤더가 잘못되었습니다")
    major, byteorder, sector_shift, mini_shift = struct.unpack_from("<4H", data, 26)
    if byteorder != 0xFFFE or mini_shift != 6 or (major, sector_shift) not in {(3, 9), (4, 12)}:
        raise ExtractionError("malformed", "OLE 버전 또는 sector 설정이 잘못되었습니다")
    sector_size = 1 << sector_shift
    if len(data) < sector_size or len(data) % sector_size:
        raise ExtractionError("malformed", "OLE 파일 길이가 sector 경계와 맞지 않습니다")
    sectors = len(data) // sector_size - 1
    for offset in (40, 44, 64, 72):
        if struct.unpack_from("<I", data, offset)[0] > sectors:
            raise ExtractionError("malformed", "OLE sector 개수가 실제 파일 범위를 넘습니다")


def parse_project_bytes(data):
    """Worker-only parser; avoid extract_macros(), which scans orphan streams."""
    try:
        from oletools import olevba
    except ImportError:
        return outcome("dependency_missing", "VBA 원문 추출에는 승인된 Python 환경의 oletools가 필요합니다. 자동 설치하지 않았습니다")
    parser, original = None, olevba.decompress_stream
    expanded = 0

    def bounded_decompress(compressed):
        nonlocal expanded
        expanded += decompressed_size(compressed)
        if expanded > MAX_TOTAL_SOURCE:
            raise ExtractionError("limit_exceeded", "VBA 전체 원문 해제 크기가 한도를 넘습니다")
        return original(compressed)

    try:
        check_ole_header(data)
        olevba.decompress_stream = bounded_decompress  # Adapter only in this child.
        parser = olevba.VBA_Parser("main-vbaProject.bin", data=data, relaxed=False, disable_pcode=True)
        ole = parser.ole_file
        if ole is None or parser.ole_subfiles:
            raise ExtractionError("malformed", "단일 VBA OLE 프로젝트가 아닙니다")
        streams = ole.listdir(streams=True, storages=False)
        if len(streams) > 1024 or sum(ole.get_size(path) for path in streams) > 32 * 1024 * 1024:
            raise ExtractionError("limit_exceeded", "OLE 스트림 개수 또는 크기가 한도를 넘습니다")
        by_name = {"/".join(path).casefold(): path for path in streams}
        if "project" not in by_name or "vba/dir" not in by_name:
            raise ExtractionError("malformed", "주 VBA 프로젝트의 PROJECT/VBA/dir 스트림이 없습니다")
        project = olevba.VBA_Project(ole, "", "/".join(by_name["project"]), "/".join(by_name["vba/dir"]), relaxed=False)
        project.parse_project_stream()
        modules, seen, total = [], set(), 0
        for _, _, _ in project.parse_modules():
            if project.modules_count > MAX_MODULES:
                raise ExtractionError("limit_exceeded", "VBA 모듈 수가 64개 한도를 넘습니다")
            module = project.modules[-1]
            name = module.name
            if not isinstance(name, str) or not name or name.casefold() in seen:
                raise ExtractionError("malformed", "VBA 모듈 이름이 없거나 중복됩니다")
            seen.add(name.casefold())
            path = module.code_path or ""
            if not re.fullmatch(r"VBA/[^/\\\x00]+", path, re.I):
                raise ExtractionError("malformed", "VBA 모듈 스트림이 주 프로젝트 범위를 벗어났습니다")
            # Empty document modules count too. A missing nonempty stream is not
            # silently represented as empty text.
            raw = module.code_raw
            if raw is None:
                stream_size = ole.get_size(path)
                if module.textoffset != stream_size:
                    raise ExtractionError("malformed", "VBA 모듈 원문을 완전하게 읽지 못했습니다")
                raw = b""
            try:
                source = raw.decode(project.codec, errors="strict")
            except (UnicodeError, LookupError) as exc:
                raise ExtractionError("decode_error", "프로젝트 코드페이지로 VBA 원문을 손실 없이 읽지 못했습니다") from exc
            encoded = source.encode("utf-8")
            total += len(encoded)
            if len(encoded) > MAX_SOURCE or total > MAX_TOTAL_SOURCE:
                raise ExtractionError("limit_exceeded", "UTF-8 VBA 원문 크기가 한도를 넘습니다")
            extension = project.module_ext.get(name.lower(), "vba")
            modules.append({"name": name, "relative_path": module_path(len(modules) + 1, name, extension),
                            "module_type": extension, "stream_path": path, "source": source,
                            "source_sha256": digest(encoded), "original_source_sha256": digest(raw),
                            "source_encoding": project.codec, "decoded_with_replacement": False,
                            "metadata_replacement_character": "\ufffd" in name,
                            "source_bytes": len(encoded), "line_count": len(source.splitlines())})
        if not modules or len(modules) != project.modules_count:
            raise ExtractionError("malformed", "VBA 프로젝트의 모듈 원문을 모두 확인하지 못했습니다")
        result = outcome("extracted", "주 통합문서의 VBA 원문을 실행 없이 추출했습니다")
        result.update(modules=modules, module_count=len(modules), source_encoding=project.codec,
                      decoded_with_replacement=False, source_bytes=total,
                      limitations=["VBA 원문만 추출하며 컴파일 코드(p-code)와의 동일성·VBA stomping은 검사하지 않습니다.",
                                   "UserForm의 UI·FRX 리소스와 내장 외부 문서는 추출하지 않습니다.",
                                   "프로젝트 잠금 해제·암호 추측·매크로 실행은 하지 않습니다."])
        return result
    except ExtractionError as exc:
        return outcome(exc.status, str(exc))
    except Exception as exc:
        return outcome("malformed", "VBA 프로젝트 구조를 해석하지 못했습니다", error_type=type(exc).__name__)
    finally:
        olevba.decompress_stream = original
        if parser is not None:
            parser.close()


def run_worker(data, timeout, python_executable=None):
    command = [str(python_executable or sys.executable), "-X", "utf8", "-B", str(Path(__file__).resolve()), "--worker"]
    payload = base64.b64encode(data)
    kwargs = {"input": payload, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
              "timeout": timeout, "check": False}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        process = subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired:
        return outcome("timeout", "VBA 원문 추출 제한 시간이 지나 작업자를 종료했습니다")
    except OSError as exc:
        return outcome("worker_unavailable", "VBA 추출용 Python 작업자를 시작하지 못했습니다", error_type=type(exc).__name__)
    if process.returncode != 0 or len(process.stdout) > MAX_WORKER_OUTPUT:
        return outcome("worker_failed", "VBA 추출 작업자가 정상 결과를 반환하지 못했습니다")
    try:
        result = json.loads(process.stdout.decode("utf-8", errors="strict"))
    except (ValueError, UnicodeError):
        return outcome("worker_failed", "VBA 추출 작업자의 결과 형식이 잘못되었습니다")
    if not isinstance(result, dict) or not isinstance(result.get("modules"), list):
        return outcome("worker_failed", "VBA 추출 작업자의 결과 계약이 잘못되었습니다")
    return result


def extract_vba(source, *, timeout=20, python_executable=None):
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0 or timeout > 120:
        raise ValueError("VBA 추출 시간은 0초 초과 120초 이하여야 합니다")
    source = Path(source)
    identity = {}
    try:
        if source.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ExtractionError("unsupported_format", "단일 xlsx/xlsm 파일을 지정하세요")
        if source.stat().st_size > MAX_CONTAINER:
            raise ExtractionError("limit_exceeded", "입력 파일이 64 MiB 한도를 넘습니다")
        with source.open("rb") as stream:
            container = stream.read(MAX_CONTAINER + 1)
        identity["container_sha256"] = digest(container)
        part, content, workbook = main_vba_part(container)
        identity.update(vba_part=part, workbook_part=workbook)
        if content is None:
            result = outcome("no_vba", "주 통합문서에 연결된 VBA 프로젝트가 없습니다")
        else:
            identity["vba_sha256"] = digest(content)
            result = run_worker(content, timeout, python_executable)
        with source.open("rb") as stream:
            after = stream.read(MAX_CONTAINER + 1)
        if digest(after) != identity["container_sha256"]:
            return outcome("source_changed", "처리 중 원본이 변경되어 추출 결과를 사용하지 않습니다", **identity)
        return dict(result, **identity, source_unchanged=True)
    except ExtractionError as exc:
        return outcome(exc.status, str(exc), **identity)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        return outcome("malformed", "파일 또는 ZIP part를 읽지 못했습니다", error_type=type(exc).__name__, **identity)


def publish_sources(result, output):
    modules = result.get("modules", [])
    if result.get("status") != "extracted" and modules:
        raise ValueError("미완료 추출 결과에 원문 모듈이 포함되어 있습니다")
    if result.get("status") == "extracted" and not modules or len(modules) > MAX_MODULES:
        raise ValueError("VBA 원문 모듈 수가 잘못되었습니다")
    seen, total = set(), 0
    for module in modules:
        path, source = module.get("relative_path", ""), module.get("source")
        if (not re.fullmatch(r"modules/[\w-]+\.(?:bas|cls)", path) or path.casefold() in seen
                or not isinstance(source, str)):
            raise ValueError("VBA 원문 저장 경로 또는 본문이 잘못되었습니다")
        raw = source.encode("utf-8")
        if len(raw) > MAX_SOURCE or digest(raw) != module.get("source_sha256"):
            raise ValueError("VBA 원문의 크기 또는 해시가 맞지 않습니다")
        seen.add(path.casefold())
        total += len(raw)
    if total > MAX_TOTAL_SOURCE:
        raise ValueError("VBA 원문 전체 크기가 한도를 넘습니다")
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("기존 VBA 추출 폴더를 덮어쓰지 않습니다")
    output.mkdir(parents=True, exist_ok=False)
    if modules:
        (output / "modules").mkdir()
    paths = []
    for module in modules:
        path = output / module["relative_path"]
        with path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(module["source"])
        paths.append(path)
    manifest = dict(result, modules=[{key: value for key, value in module.items() if key != "source"} for module in modules])
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    return paths


def worker_main():
    encoded = sys.stdin.buffer.read((MAX_VBA * 4 // 3) + 8)
    if len(encoded) > (MAX_VBA + 2) // 3 * 4:
        result = outcome("limit_exceeded", "VBA 작업자 입력이 한도를 넘습니다")
    else:
        try:
            data = base64.b64decode(encoded, validate=True)
            if len(data) > MAX_VBA or not data.startswith(OLE_MAGIC):
                raise ValueError()
            # Suppress dependency diagnostics and avoid collecting them in memory.
            with open(os.devnull, "w") as discard, contextlib.redirect_stdout(discard), contextlib.redirect_stderr(discard):
                logging.disable(logging.CRITICAL)
                result = parse_project_bytes(data)
        except Exception as exc:
            result = outcome("malformed", "VBA 작업자 입력을 해석하지 못했습니다", error_type=type(exc).__name__)
    payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_WORKER_OUTPUT:
        payload = json.dumps(outcome("limit_exceeded", "VBA 작업자 출력이 한도를 넘습니다"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(payload)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="OOXML 주 통합문서의 VBA 원문만 실행 없이 추출합니다")
    parser.add_argument("source", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return worker_main()
    if not args.source:
        parser.error("입력 파일을 지정하세요")
    try:
        result = extract_vba(args.source, timeout=args.timeout)
        if args.output and result["status"] == "extracted":
            publish_sources(result, args.output)
        visible = dict(result, modules=[{k: v for k, v in module.items() if k != "source"} for module in result["modules"]])
        print(json.dumps(visible, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"extracted", "no_vba"} else 2
    except (OSError, ValueError) as exc:
        print(json.dumps(outcome("not_processed", str(exc)), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
