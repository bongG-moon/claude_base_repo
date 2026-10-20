"""On-demand CLI bridge to the generated, self-contained Excel analysis skill."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

from .business_safety import safe_path


def read_only_arguments(arguments: list[str]) -> bool:
    """Classify a parsed trusted invocation, never grant tool permission.

    Output generation and unknown/duplicate/invalid flags remain ordinary work.
    This does not read any path or import Excel dependencies.
    """
    if arguments[:2] != ['business', 'excel-analyze']:
        return False
    if arguments[2:] == ['--help']:
        return True
    fields = {}
    switches = set()
    allowed = {'--file', '--state-root', '--plan', '--reader', '--excel-timeout', '--sample-rows', '--context-chars', '--target', '--layout'}
    index = 2
    while index < len(arguments):
        key = arguments[index]
        if key in {'--inspect', '--context-only'}:
            if key in switches:
                return False
            switches.add(key)
            index += 1
            continue
        if key not in allowed or (key in fields and key != '--target') or index + 1 == len(arguments):
            return False
        value = arguments[index + 1]
        if not value or value.startswith('--'):
            return False
        fields[key] = value
        index += 2
    if len(switches) != 1 or '--file' not in fields:
        return False
    if Path(fields['--file']).suffix.lower() not in {'.xlsx', '.xlsm'}:
        return False
    if fields.get('--reader', 'auto') not in {'auto', 'openpyxl', 'xlwings'}:
        return False
    if fields.get('--layout', 'compact') not in {'compact', 'detailed'}:
        return False
    for key, low, high in (('--excel-timeout', 10, 300), ('--sample-rows', 0, 1000), ('--context-chars', 1024, 50000)):
        if key in fields and (not re.fullmatch(r'[0-9]+', fields[key]) or not low <= int(fields[key]) <= high):
            return False
    return True


def analyze(args) -> dict:
    try:
        source = safe_path(args.file)
        output = safe_path(args.output) if args.output else None
        plan = safe_path(args.plan) if args.plan else None
        if not source.is_file() or (plan and not plan.is_file()):
            return {"ok": False, "status": "input_required", "code": "excel_input_not_found",
                    "message": "지정한 입력 파일 또는 표 범위 명세가 없습니다. 첨부한 정확한 경로만 확인해 주세요. DRM으로 단정하거나 PC를 검색하지 마세요.",
                    "retryAllowed": False}
    except (OSError, ValueError):
        return {"ok": False, "status": "blocked", "code": "excel_input_path_unavailable",
                "message": "지정한 파일 경로나 접근 권한을 확인하지 못했습니다. 권한 변경이나 다른 읽기 방식으로 재시도하지 않았습니다.",
                "retryAllowed": False}
    if not 10 <= args.excel_timeout <= 300 or not 0 <= args.sample_rows <= 1000 or not 1024 <= args.context_chars <= 50000:
        return {"ok": False, "status": "input_required", "code": "invalid_excel_limits",
                "message": "Excel 대기는 10~300초, 표본은 0~1000행, 요약은 1024~50000자로 지정해 주세요."}
    script = Path(__file__).resolve().parents[2] / "skills" / "excel-to-pipeline" / "scripts" / "excel_pipeline.py"
    if not script.is_file():
        return {"ok": False, "status": "failed", "code": "excel_skill_incomplete",
                "message": "엑셀 분석 실행 파일이 없습니다. 설치 배포본을 다시 적용해 주세요. 파일 경로를 추측해 실행하지 마세요."}
    command = [sys.executable, "-I", "-X", "utf8", "-B", str(script), str(source),
               "--reader", args.reader, "--excel-timeout", str(args.excel_timeout),
               "--sample-rows", str(args.sample_rows), "--context-chars", str(args.context_chars)]
    # -I omits the script directory from sys.path. The shipped modules are siblings;
    # use a fixed bootstrap that restores only that trusted installed directory.
    bootstrap = ("import runpy,sys; from pathlib import Path; "
                 "p=Path(sys.argv[1]).resolve(); sys.path.insert(0,str(p.parent)); "
                 "sys.argv=sys.argv[1:]; runpy.run_path(str(p),run_name='__main__')")
    command[5:5] = ["-c", bootstrap]
    if output:
        command += ["--output", str(output)]
    elif args.context_only:
        command += ["--context-only"]
    else:
        command += ["--inspect"]
    if plan:
        command += ["--plan", str(plan)]
    layout = getattr(args, 'layout', 'compact')
    command += ["--layout", layout]
    if getattr(args, 'diagnostics', False):
        command += ["--diagnostics"]
    for target in getattr(args, 'target', []):
        command += ["--target", target]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                               check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode:
        diagnostic = completed.stderr.strip()
        missing = re.search(r"ModuleNotFoundError: No module named ['\"](openpyxl|xlwings|oletools|olefile|win32com)(?:\.[^'\"]*)?['\"]", diagnostic)
        if missing:
            return {"ok": False, "status": "input_required", "code": "excel_dependency_missing",
                    "dependency": missing.group(1), "python": sys.executable,
                    "message": f"현재 Python에 {missing.group(1)}이 없습니다. 승인된 환경에 필요한 패키지만 준비해 주세요. 자동 설치나 설정 변경은 하지 않았습니다."}
        try:
            failure = json.loads(diagnostic)
        except (json.JSONDecodeError, ValueError):
            failure = {"message": "엑셀 분석을 끝내지 못했습니다. 원본을 저장하거나 다른 읽기 방식으로 재시도하지 않았습니다."}
        return {"ok": False, "status": "failed", "code": "excel_analysis_incomplete",
                "message": str(failure.get("message", "엑셀 분석을 끝내지 못했습니다."))[:2000],
                "retryAllowed": False}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "status": "failed", "code": "excel_result_invalid",
                "message": "분석 결과를 확인하지 못했습니다. 같은 작업을 자동으로 다시 실행하지 마세요.",
                "retryAllowed": False}
    response = {"ok": True, "status": "completed", "context" if args.context_only else "summary": result,
                "sourceModified": False, "macrosExecuted": False}
    if output:
        detail = output if layout == 'detailed' else output / '_details'
        response.update(output=str(output), modelContext=str(detail / "model_context.json"),
                        entryPoint=str(output / "main.py"), dataDirectory=str(output / "DATA"),
                        processDirectory=str(output / "PROCESS"), readme=str(output / "README.md"))
        if layout == 'detailed':
            response.update(report=str(output / 'report.md'), transform=str(output / 'transform.py'))
    return response
