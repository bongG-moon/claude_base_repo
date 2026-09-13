"""Create a new Desktop lab from a verified offline bundle; never install it.

Usage: python scripts/build-test-lab.py --destination <new-directory>
Only standard-library dependencies. Refuses to overwrite existing destinations.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import shutil
import zipfile


REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "scripts" / "test-lab"
EXTERNAL = {"T14", "T15", "T17", "T18", "T19", "T24", "T28", "T29", "T32"}


def write(path: Path, body: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding=encoding, newline="\n") as stream:
        stream.write(body)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def make_fixtures(work: Path) -> None:
    organize = work / "01-folder-organize"
    write(organize / "안내.txt", "가상 연습 문서입니다. 정리 프로그램으로 이동 후 다시 복구할 수 있어야 합니다.\n")
    write(organize / "원본보존.txt", "연습용 내용입니다. 이동과 되돌리기에서 이 내용은 바뀌면 안 됩니다.\n")
    write(organize / "회의 메모.md", "# 가상 회의\n\n9월 연습 보고서를 검토합니다. 실제 회사 업무가 아닙니다.\n")
    write_json(organize / "분류미지원.json", {"synthetic": True, "note": "JSON은 기본 파일 정리 대상이 아닙니다."})
    write(organize / "그대로둘것" / "안내.txt", "하위 폴더 보존 확인용입니다. 바로 아래 파일만 정리할 때는 이동하지 않습니다.\n")
    with zipfile.ZipFile(organize / "가상자료.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", "Synthetic test archive. No executable or company data.\n")
    write_json(work / "02-report-input" / "monthly-results.json", {
        "synthetic": True, "source": "사용자가 제시한 검증용 가상 실적", "unit": "건",
        "rows": [{"month": "6월", "target": 100, "actual": 90},
                 {"month": "7월", "target": 100, "actual": 110},
                 {"month": "8월", "target": 100, "actual": 130}],
    })
    write(work / "02-report-input" / "meeting-notes.md", "# 가상 팀 회의 메모\n\n실적 수치는 monthly-results.json에 있습니다.\n실제 회사 실적이 아닙니다. 수치 변화의 원인은 조사하지 않았습니다.\n담당자 이름, 고객명, 예산은 제공되지 않았습니다. 빈 정보를 추측하지 않습니다.\n")
    write(work / "03-presentation-input" / "brief.md", "# 가상 발표 자료 제작 요청\n\n자료: ../02-report-input/monthly-results.json\n3장 구성: 핵심 요약 / 월별 표 / 월별 실적 차트\n각 월 목표와 실적의 단위는 건입니다.\n제목, 표, 차트는 편집 가능해야 합니다. 전체 슬라이드를 사진으로 만들지 않습니다.\n참고 회사 PPT 양식은 제공하지 않은 시험입니다. 실제 PPT 파일은 T13에서 생성합니다.\n")
    now = datetime.now(timezone(timedelta(hours=9)))
    meeting = now + timedelta(days=1)
    for number, title, body in [
        (1, "CA_메일검증_20260910 CA-PILOT-ONLY 가상 회의", f"가상 연습 메일입니다. 회의는 {meeting:%Y-%m-%d} 오후 2시, 회의실 A입니다. 준비물은 가상 일정표입니다."),
        (2, "CA-PILOT-ONLY 가상 보고서 보완", "가상 연습 메일입니다. 월간 보고서에는 목표와 실적을 함께 표시해주세요. 원인은 확인되지 않았으므로 추측하지 마세요."),
        (3, "연습 검색 제외 대상", "가상 연습 메일입니다. 이 메일은 다른 주제의 개인 메모 예시입니다."),
    ]:
        mail = EmailMessage(policy=SMTP)
        mail["From"] = "training-sender@example.invalid"
        mail["To"] = "training-recipient@example.invalid"
        mail["Subject"] = title
        mail["Date"] = format_datetime(now - timedelta(hours=number))
        mail["Message-ID"] = f"<company-agent-lab-{number}@example.invalid>"
        mail.set_content(body + "\n실제 송수신하지 않은 로컬 파일입니다.\n", charset="utf-8")
        if number == 1:
            mail.add_attachment("가상 일정표\n14:00 회의 시작\n14:30 보고서 검토\n", subtype="plain", filename="가상일정표.txt", charset="utf-8")
        path = work / "04-mail-samples" / f"sample-{number:02d}.eml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(mail.as_bytes())
    write(work / "04-mail-samples" / "READ_ME_FIRST.md", "# 로컬 메일 예시와 실제 Outlook 시험은 다릅니다\n\n이 EML 파일은 실제로 발송하거나 메일함에 가져오지 않았습니다. 로컬 요약 시험 L01에만 사용합니다.\nOutlook 검색 시험 T15/T32는 본인 메일함에 AI 조회가 허용된 연습 메일이 있어야 합니다. 없으면 미실행입니다.\n회사에서 허용하는 정상 절차로 본인이 준비하세요. 이 파일의 수신자 주소는 사용할 수 없는 가상 주소입니다.\n시험용 제목: CA_메일검증_20260910 CA-PILOT-ONLY\n본문 예시: 회의는 내일 오후 2시, 회의실 A, 준비물은 가상 일정표입니다.\n메일 준비 날짜를 기준으로 검색 기간을 선택하세요. 자동 발송/가져오기/PST 이동은 하지 않습니다.\n")
    write_json(work / "05-protection-simulation" / "mock-result.json", {
        "simulation_only": True, "not_real_drm_detection": True,
        "body": "회의는 내일 오후2시, 준비물은 일정표", "attachment": {"read": False, "reason": "보호 설정 때문에 읽지 못함 (가상 상황)"},
    })
    write(work / "06-knowledge-input" / "glossary-example.md", "# 가상 용어 예시\n\n## 가상검토건\n검토 대기 목록에 등록한 연습 문서 하나를 뜻합니다.\n출처: 테스트 환경에서 만든 가상 정의\n실제 회사 용어·DB 정보가 아닙니다. 이 파일은 입력 예시이며 활성 개인 지식에 미리 등록하지 않았습니다.\n")
    write_json(work / "06-knowledge-input" / "table-example.json", {
        "synthetic": True, "table": "LAB_MONTHLY_RESULTS", "columns": ["month", "target", "actual"],
        "note": "설명용 가상 테이블입니다. 실제 DB나 corp-db-read 연결을 만들지 않았습니다.",
    })
    (work / "07-project-factory").mkdir(parents=True)
    (work / "outputs").mkdir()
    write(work / "README.md", "# 가상 업무 연습 작업 폴더\n\n실제 회사 자료가 아닌 연습 자료만 있습니다.\n정리 대상은 01-folder-organize, 보고서 입력은 02-report-input, 발표 입력은 03-presentation-input입니다.\n결과물은 outputs에 새 이름으로 저장합니다. 07-project-factory는 새 프로젝트 하네스 제작 시험용입니다.\n상위 operator 폴더는 사람이 보는 판정 기준이므로 요청 없이 읽지 않습니다.\n로컬 메일 예시는 실제 Outlook 연결, 가상 보호 오류는 실제 DRM 검증을 대신하지 않습니다.\n파일 이동/삭제/덮어쓰기나 메일 동작은 사용자 지시와 기존 승인 절차를 따릅니다.\n")


def lab_cases(source: str) -> list[dict]:
    cases = []
    for match in re.finditer(r"^## (T\d{2}) (.+)\n([\s\S]*?)(?=^## |\Z)", source, re.M):
        case_id, title, body = match.groups()
        prompts = re.findall(r"```text\n([\s\S]*?)\n```", body)
        stages, previous_end = [], 0
        for block in re.finditer(r"```text\n[\s\S]*?\n```", body):
            between = body[previous_end:block.start()].strip()
            hint = between.split("\n\n")[-1].replace("**", "") if between else "같은 대화에서 이어서 실행합니다."
            stages.append(hint[:320])
            previous_end = block.end()
        if case_id == "T09":
            title = "준비된 연습 폴더의 정리안"
            prompts = ["현재 작업 폴더의 01-folder-organize는 미리 준비한 가상 파일 정리 연습 폴더야.\n새 폴더나 파일을 만들지 말고 Company Agent 파일 정리 기능으로 바로 아래 파일의 종류별 정리안만 보여줘. 아직 이동하지 마.\nTXT·MD 문서는 문서, ZIP은 압축자료로 분류되는지 확인해줘. 하위 폴더 그대로둘것과 JSON 파일은 건드리지 마."]
            body = "원래 T09의 CSV 생성 대신 TXT·MD·ZIP이 준비된 변형입니다. 새 파일을 만들지 않습니다.\n정상 기준: 문서 3개, 압축자료 1개 정리안만 제시합니다. JSON과 하위 폴더 파일은 보존합니다. T10 취소 후 파일 위치가 같아야 합니다."
            stages = ["새 대화에서 시작합니다. 준비된 파일을 새로 만들지 말고 정리안만 확인합니다."]
        if case_id in {"T10", "T11"}:
            body = body.replace("TXT·CSV", "TXT·MD·ZIP").replace("TXT·CSV", "TXT·MD·ZIP")
        additions = {
            "T12": "가상 실적 원본은 현재 작업 폴더 02-report-input/monthly-results.json이고, 새 결과는 outputs에 저장해줘.",
            "T13": "입력은 02-report-input/monthly-results.json과 03-presentation-input/brief.md야. 새 결과는 outputs에 저장해줘.",
            "T22": "지정할 새 연습 프로젝트는 현재 작업 폴더의 07-project-factory야. 이 폴더만 대상으로 하고 먼저 기존 파일을 확인해줘.",
            "T33": "저장 위치는 현재 작업 폴더의 outputs야. 새 이름으로 만들어줘.",
            "T29": "진행한다면 입력은 02-report-input/monthly-results.json, 결과 위치는 outputs야. 지금은 선택을 먼저 물어봐.",
        }
        if case_id in additions:
            prompts[0] += "\n" + additions[case_id]
        if case_id in {"T10", "T11"}:
            prompts = [p + "\n대상은 현재 작업 폴더의 01-folder-organize만이야." for p in prompts]
        cases.append({"id": case_id, "title": title, "body": body, "prompts": prompts,
                      "stages": stages, "external": case_id in EXTERNAL})
    if len(cases) != 34 or [c["id"] for c in cases] != [f"T{i:02d}" for i in range(1, 35)]:
        raise ValueError("Expected T01 through T34 in the source chat set.")
    cases.append({"id": "L01", "title": "로컬 메일 파일 요약 (Outlook 없이)", "external": False,
                  "stages": ["새 대화. 실제 Outlook 대신 가상 로컬 파일만 사용합니다."],
                  "body": "선택 추가 시험입니다. Outlook 연결 시험 T15/T32와 별개입니다. 준비된 3개 EML의 본문과 첨부 읽기 범위를 정확하게 설명하는지 봅니다. 실행한 파일 읽기를 실제 Outlook 연결/검색으로 표현하면 개선필요입니다.",
                  "prompts": ["현재 작업 폴더의 04-mail-samples에 있는 sample-01.eml, sample-02.eml, sample-03.eml은 가상 로컬 메일 파일이야.\n이 3개 파일만 읽어서 회의 일정과 해야 할 일을 요약해줘. 첨부를 읽었는지 목록만 봤는지 구분해줘.\nOutlook 연결, 메일 발송·가져오기·이동·삭제는 하지 마. 실제 메일함을 검색했다고 표현하지 마. 원본 파일은 수정하지 마."]})
    return cases


def render_cases(cases: list[dict], operator: Path) -> tuple[str, str]:
    articles, nav = [], []
    for case in cases:
        cid = case["id"]
        nav.append(f'<a href="#{cid}">{cid}</a>')
        prompt_html = []
        for index, prompt in enumerate(case["prompts"], 1):
            pid = f"{cid}-{index}"
            write(operator / "requests" / f"{pid}.txt", prompt + "\n")
            stage = html.escape(case["stages"][index - 1])
            prompt_html.append(f'<div class="prompt"><h3>{cid} · 요청 {index}</h3><p class="muted"><strong>{stage}</strong></p><pre id="{pid}">{html.escape(prompt)}</pre><button type="button" class="copy" data-target="{pid}">이 요청만 복사</button></div>')
        # Keep every narrative instruction, including new-chat boundaries. Exclude code
        # from this folded narrative because the executable prompts are separate above.
        guidance = re.sub(r"```text\n[\s\S]*?\n```", "[이 단계의 요청은 아래 회색 상자]", case["body"])
        group = "external" if case["external"] else "local"
        tag = "회사 환경 / 준비 후 선택 실행" if case["external"] else "로컬 자료 / 설치 후 실행"
        options = "".join(f'<option>{status}</option>' for status in ["미실행", "정상", "개선필요", "환경차단", "판단보류"])
        articles.append(f'<article id="{cid}" class="{group}" data-group="{group}"><h2>{cid} {html.escape(case["title"])}</h2><span class="tag">{tag}</span><details><summary>진행 안내·판정 기준 (사람만 확인)</summary><div class="readme">{html.escape(guidance)}</div></details>{"".join(prompt_html)}<label>이 시험의 판정 <select aria-label="{cid} 판정">{options}</select></label><label for="note-{cid}">최초 응답 / 내가 선택한 것 / 실제 결과 / 오류 (민감 정보 제외)</label><textarea id="note-{cid}" placeholder="아직 실행하지 않았으면 비워두세요."></textarea></article>')
    return "\n".join(articles), "".join(nav)


def build(destination: Path, bundle: Path) -> dict:
    helper_spec = importlib.util.spec_from_file_location("test_lab_support", TEMPLATES / "lab.py")
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    destination = helper.safe(destination)
    if destination.exists():
        raise FileExistsError("Existing destination is preserved; choose a new folder: " + str(destination))
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("bundle-manifest.json"))
        version = manifest["coreVersion"]
        entries = archive.infolist()
        for entry in entries:
            rel = Path(entry.filename.replace("\\", "/"))
            if rel.is_absolute() or ".." in rel.parts or ":" in str(rel) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Unsafe bundle entry: " + entry.filename)
        # No input writes happen until source and archive paths are checked.
        source = (REPO / "docs" / "VALIDATION_CHAT_SET.md").read_text(encoding="utf-8-sig")
        declared_version = re.search(r"대상 버전 ([\d.]+)", source)
        if not declared_version or declared_version.group(1) != version:
            raise ValueError("The chat-set version must match the installer bundle version.")
        cases = lab_cases(source)
        destination.mkdir(parents=True)
        archive.extractall(destination / "installer" / "package")
    shutil.copyfile(bundle, destination / "installer" / bundle.name)
    for name in ["lab.py", "Start-Lab.ps1"]:
        # Windows PowerShell 5.1 needs a BOM to read Korean script messages.
        write(destination / name, (TEMPLATES / name).read_text(encoding="utf-8"), "utf-8-sig" if name.endswith(".ps1") else "utf-8")
    for name, action in [("01_START_TEST.cmd", "Menu"), ("02_INSTALL_PROJECT.cmd", "Install"), ("03_CHECK_FILES.cmd", "Check")]:
        write(destination / name, '@echo off\nsetlocal\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -File "%~dp0Start-Lab.ps1" -Action ' + action + '\nset "LAB_EXIT=%ERRORLEVEL%"\nif not "%LAB_EXIT%"=="0" echo Stopped. Keep the message above for diagnosis.\npause\nexit /b %LAB_EXIT%\n', "ascii")
    make_fixtures(destination / "workspace")
    operator = destination / "operator"
    operator.mkdir()
    docs = {"VALIDATION_CHAT_SET.md": "ORIGINAL_CHAT_SET.md", "Company-Agent-운영-검증-채팅.html": "ORIGINAL_CHAT_SET.html",
            "VALIDATION_RESULTS_TEMPLATE.md": "BLANK_RESULTS.md", "Company-Agent-사용자-안내서.html": "USER_GUIDE.html",
            "UPDATE_1.3.3.md": "UPDATE_GUIDE.md"}
    for source_name, target_name in docs.items():
        shutil.copyfile(REPO / "docs" / source_name, operator / target_name)
    articles, nav = render_cases(cases, operator)
    dashboard = (TEMPLATES / "dashboard.html").read_text(encoding="utf-8")
    write(destination / "00_START_HERE.html", dashboard.replace("@@VERSION@@", html.escape(version)).replace("@@CASES@@", articles).replace("@@NAV@@", nav))
    organize = destination / "workspace" / "01-folder-organize"
    inputs = {p.relative_to(destination / "workspace").as_posix(): digest(p)
              for p in sorted((destination / "workspace").rglob("*")) if p.is_file() and not p.is_relative_to(organize)}
    write_json(operator / "baseline.json", {"organizer": {p.relative_to(organize).as_posix(): digest(p)
              for p in sorted(organize.rglob("*")) if p.is_file()}, "inputs": inputs})
    meta = {"schemaVersion": 1, "kind": "company-agent-test-lab", "coreVersion": version,
            "createdAt": datetime.now(timezone.utc).isoformat(), "bundleName": bundle.name,
            "bundleSha256": digest(bundle), "cases": len(cases), "installedByBuilder": False}
    write_json(destination / "lab.json", meta)
    write(destination / "먼저읽기.txt", "Company Agent 연습실\n\n1. 01_START_TEST.cmd를 더블클릭하고 3을 선택하세요.\n2. 처음이면 프로젝트 설치 안내에 동의할 때 1을 입력하세요.\n3. 열린 질문 화면에서 T01부터 요청 하나씩 Claude에 복사하세요.\n4. 새 대화는 /exit 후 메뉴 3으로 다시 시작하세요.\n5. 결과는 질문 화면의 결과 내려받기로 저장하세요.\n\n회사 자료나 본인 메일함은 건드리지 않고 준비했습니다.\n설치 후에 연습 기억은 personal-state에 만들어집니다.\nPython 3.11+와 이미 사용하는 Claude Code가 필요합니다.\nOutlook·DB·DRM 등 회사 환경 시험은 별도 준비가 필요합니다.\n폴더를 회사 PC로 옮긴다면 설치 전에 전체 폴더를 승인된 경로로 복사하세요.\n설치 후에는 이 폴더를 임의로 이동/삭제하지 마세요.\n")
    result = helper.check(destination, installation=False)
    if not result["fixtureEnvironmentReady"] or not result["fixtures"]["originalLocations"]:
        raise RuntimeError("Generated fixture integrity check failed.")
    return {"destination": str(destination), "cases": len(cases), "prompts": sum(len(c["prompts"]) for c in cases),
            "fixtureFiles": len(inputs) + len(list(organize.rglob("*.*"))), "installed": False, "bundleSha256": meta["bundleSha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--bundle", type=Path, default=REPO / "dist" / "company-agent-1.3.3-2026.09.03.zip")
    options = parser.parse_args()
    print(json.dumps(build(options.destination, options.bundle), ensure_ascii=True, indent=2))
