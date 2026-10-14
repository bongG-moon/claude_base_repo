"""Read VBA source text for migration planning. Never executes or translates VBA.

This is an index of declarations and lexical hints, not a VBA parser or a proof
of behavior. The caller must read the referenced procedures before conversion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
DECLARATION = re.compile(r"^\s*(?:(?:Public|Private|Friend|Static)\s+)*(Sub|Function|Property\s+(?:Get|Let|Set))\s+([\w]+)\b", re.I)
ENDING = re.compile(r"^\s*End\s+(Sub|Function|Property)\b", re.I)
EVENTS = re.compile(r"^(?:Auto_Open|Auto_Close|Workbook_.+|Worksheet_.+|UserForm_.+)$", re.I)
HINTS = {
    "external_or_process_action": r"\b(?:Shell|CreateObject|GetObject|Kill|FileCopy|SaveAs|RefreshAll|FollowHyperlink)\b|\bDeclare\b.*\bLib\b|\bOpen\b.+\bFor\b",
    "dynamic_dispatch": r"\bApplication\s*\.\s*Run\b|\bCallByName\b|\bEvaluate\b",
    "user_interaction": r"\b(?:MsgBox|InputBox|FileDialog|GetOpenFilename)\b",
    "calculation_order": r"\b(?:Calculate|CalculateFull|CalculateFullRebuild|Calculation|EnableEvents|Formula|FormulaR1C1)\b",
    "rounding_semantics": r"\bRound\b",
    "error_handling": r"\bOn\s+Error\b|\bResume\b",
}


def comment_free(line):
    """Remove apostrophe/REM comments without damaging quoted VBA strings."""
    if re.match(r"^\s*Rem(?:\s|$)", line, re.I):
        return ""
    result, quoted, index = [], False, 0
    while index < len(line):
        char = line[index]
        if char == '"':
            if quoted and index + 1 < len(line) and line[index + 1] == '"':
                result.extend(['"', '"'])
                index += 2
                continue
            quoted = not quoted
        if char == "'" and not quoted:
            break
        result.append(char)
        index += 1
    return "".join(result)


def without_strings(text):
    return re.sub(r'"(?:[^"\n]|"")*"', '""', text)


def inspect_sources(paths, encoding="utf-8-sig"):
    if not paths or len(paths) > 64:
        raise ValueError("VBA 원문 파일 1~64개를 지정하세요.")
    sources, total = [], 0
    for supplied in paths:
        source = Path(supplied).resolve()
        if source.suffix.lower() not in {".bas", ".cls", ".frm", ".vba"}:
            raise ValueError("내보낸 VBA 원문(.bas/.cls/.frm/.vba)을 지정하세요. 워크북 내장 VBA 추출은 별도 단계입니다.")
        size = source.stat().st_size
        total += size
        if size > MAX_SOURCE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("VBA 원문 크기가 시험판 한도를 넘습니다.")
        raw = source.read_bytes()
        text = raw.decode(encoding, errors="strict")
        sources.append({"file": source.name, "text": text, "sha256": hashlib.sha256(raw).hexdigest()})
    return _inspect_loaded_sources(sources)


def inspect_module_texts(modules):
    """Index already extracted UTF-8 source without temporary files."""
    if not modules or len(modules) > 64:
        raise ValueError("VBA 원문 모듈 1~64개가 필요합니다.")
    sources, total = [], 0
    for module in modules:
        text = module["source"]
        raw = text.encode("utf-8")
        total += len(raw)
        if len(raw) > MAX_SOURCE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("VBA 원문 크기가 시험판 한도를 넘습니다.")
        sources.append({"file": Path(module["relative_path"]).name, "text": text,
                        "sha256": hashlib.sha256(raw).hexdigest()})
    return _inspect_loaded_sources(sources)


def _inspect_loaded_sources(sources):
    modules = []
    for source in sources:
        text = source["text"]
        lines, procedures, warnings, active = text.splitlines(), [], [], None
        for number, line in enumerate(lines, 1):
            clean = comment_free(line)
            declaration = DECLARATION.match(clean)
            if declaration:
                if active:
                    warnings.append({"line": number, "reason": "nested_or_unterminated_declaration"})
                    active["end_line"] = number - 1
                    procedures.append(active)
                active = {"name": declaration.group(2), "kind": declaration.group(1),
                          "start_line": number, "end_line": None}
            if ENDING.match(clean) and active:
                active["end_line"] = number
                procedures.append(active)
                active = None
        if active:
            active["end_line"] = len(lines)
            procedures.append(active)
            warnings.append({"line": active["start_line"], "reason": "unterminated_procedure"})
        if any(re.match(r"^\s*#(?:If|Else|End)", line, re.I) for line in lines):
            warnings.append({"reason": "conditional_compilation_requires_review"})
        modules.append({"file": source["file"], "sha256": source["sha256"],
                        "line_count": len(lines), "procedures": procedures,
                        "warnings": warnings, "_lines": lines})
    known = {p["name"].lower() for m in modules for p in m["procedures"]}
    for module in modules:
        lines = module.pop("_lines")
        for proc in module["procedures"]:
            selected = [(i, comment_free(lines[i - 1])) for i in range(proc["start_line"] + 1, proc["end_line"])]
            code = "\n".join(line for _, line in selected)
            executable = without_strings(code)
            # Candidate edges only: variable/property shadowing and implicit calls
            # cannot be resolved correctly by a lexical index.
            proc["call_candidates"] = sorted(name for name in known if re.search(r"(?<![\w])" + re.escape(name) + r"\s*(?:\(|(?:\s|$))", executable, re.I))
            proc["literal_sheets"] = sorted(set(re.findall(r'\b(?:Worksheets|Sheets)\s*\(\s*"([^"\n]+)"\s*\)', code, re.I)))
            proc["literal_ranges"] = sorted(set(re.findall(r'\bRange\s*\(\s*"([^"\n]+)"\s*\)', code, re.I)))
            proc["event_entry_candidate"] = bool(EVENTS.match(proc["name"]))
            proc["review_hints"] = [{"line": number, "kind": kind}
                                    for number, line in selected for kind, pattern in HINTS.items()
                                    if re.search(pattern, without_strings(line), re.I)]
    return {"kind": "vba_source_index", "macro_executed": False, "translation_generated": False,
            "module_count": len(modules), "procedure_count": sum(len(m["procedures"]) for m in modules),
            "modules": modules,
            "limitations": ["호출·참조는 문자열 기반 후보이며 완전한 VBA 구문·자료 흐름 분석이 아닙니다.",
                            "동적 참조·이벤트·조건부 컴파일·외부 라이브러리는 원문과 실행 계약을 확인해야 합니다.",
                            "이 목록만으로 코드 안전성이나 Python 변환 완료를 판정하지 않습니다."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="VBA 원문을 실행 없이 색인합니다. Python 변환은 별도입니다.")
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--output", required=True, help="새 JSON 파일")
    args = parser.parse_args(argv)
    try:
        output = Path(args.output)
        if output.exists() or output.is_symlink():
            raise ValueError("기존 결과는 덮어쓰지 않습니다. 새 JSON 경로를 지정하세요.")
        report = inspect_sources(args.sources, args.encoding)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps({key: report[key] for key in ("kind", "module_count", "procedure_count", "macro_executed", "translation_generated")}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, LookupError) as error:
        print(json.dumps({"status": "not_processed", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
