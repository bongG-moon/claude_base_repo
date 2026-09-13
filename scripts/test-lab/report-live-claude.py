"""Render observed live results, keeping manual verdicts separate from CLI success."""
import argparse
import json
from pathlib import Path
import re

VERDICTS = {
    "T04": ("정상", "없는 파일은 없다고 답하고 독립 계산 330을 제공했습니다. Glob으로 확인했고, 파일을 만들지 않았으며 Stop은 허용했습니다."),
    "T30": ("정상", "로딩된 스킬의 폴더 정리/메일 기능을 설명한 뒤 종료했습니다. 빈 학습·accepted 보고·변경 검증 요구가 없었습니다. 실제 Outlook 사용 성공을 확인한 시험은 아닙니다."),
    "T12-choice": ("선택 안내 단계 정상", "HTML의 모양·분량·넘김 방식을 먼저 물었습니다. 파일 생성 전 선택 단계만 시험했습니다. 영어 스타일 이름 중심 표현은 초보자용 한국어 설명을 보강할 수 있습니다."),
    "T16": ("개선필요", "읽지 못한 첨부는 제외했지만 ‘발신자에게 보호 해제된 파일을 요청’하라는 안내를 덧붙였습니다. 승인된 정상 경로/담당자 확인 안내로 한정해야 합니다. 실제 DRM 감지 시험은 아닙니다."),
    "T19-policy": ("개선필요", "DB 쓰기·타인 계정 발송 거부 원칙은 답했지만, Outlook 조회 없이 Claude 로그인 이메일을 본인 Outlook 계정처럼 특정했습니다. 도구로 확인한 메일 계정과 Claude 로그인 계정을 분리해야 합니다."),
    "T33": ("부분 확인 / 승인 제한", "Markdown 파일 생성과 Read 재확인은 성공했고 실제 파일의 목표10·완료9·90%도 맞았습니다. session verify 호출은 무인 세션의 승인 제한에 막혔고 Stop 보정 요구가 2회 발생해 마지막 답변이 길어졌습니다. 검증 기록은 미작성입니다."),
    "T05-A": ("환경차단 / 추가 결함 확인", "기억 검색 명령이 무인 승인 제한에 막혔고 기억은 저장되지 않았습니다. 응답은 저장하지 못했다고 밝혔습니다. 다만 거부된 호출은 memory search인데 마지막에는 upsert가 거부됐다고 설명했고, 제안 명령의 --query도 실제 CLI 문법(위치 인자 query)과 다릅니다. 새 대화 기억 유지/학습 성공 판정은 하지 않습니다."),
    "L01": ("요약 확인 / 종료 미완료", "EML 3개와 첨부 일정의 요약 내용은 준비된 가상 자료와 일치했습니다. 하지만 디코딩 중 여러 Bash 시도 후 변경 검증이 요구되었고, 100초 제한에서 이 시험 프로세스만 종료했습니다. 최종 result 이벤트가 없어 전체 완료 판정은 하지 않습니다."),
}


def clean(value):
    return re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[이메일 가림]", str(value or ""))


def render(root):
    summaries = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "evidence").glob("*/summary.json"))]
    by_case = {s["case"]: s for s in summaries}
    if set(by_case) != set(VERDICTS):
        raise ValueError("This report expects exactly the eight reviewed live probes.")
    lines = ["# Company Agent 실제 Claude 응답 검증 결과", "", "검증일: 2026-09-12", "",
        "## 결론", "",
        "실제 Claude CLI로 8개 대화를 실행했습니다. 단순 목록 조회와 일부 결과 생성은 동작했지만, **기억 저장·업무 완료 처리까지 모두 정상이라고 판단할 수는 없습니다.** 승인 제한과 명령 작성 오류, 읽기 작업의 변경 판정, 근거 없는 Outlook 계정 특정이 확인됐습니다.", "",
        "## 다른 작업을 보호하기 위해 사용한 방식", "",
        "- 기존 설치를 갱신하지 않고 1.3.0 소스 플러그인을 `--plugin-dir`로 이번 세션에만 로딩했습니다. native Project 설치 경로의 완전한 운영 시험은 아닙니다.",
        "- 실제 응답 모델은 Claude Code 2.1.263의 `claude-sonnet-5`였습니다. 회사 HCP 모델/엔드포인트를 시험한 것은 아닙니다.",
        "- 별도 workspace/state에 가상 자료만 준비하고, 기존 로그인은 CLI의 정상 인증 경로로 사용했습니다. 인증 파일/토큰을 복사하지 않았습니다.",
        "- 기존 user/project/local 설정 로딩과 기존 MCP 연결을 제외했습니다. 실제 메일·DB 동작, 설치, 전역 권한 변경, 승인창 조작은 하지 않았습니다.",
        "- 제한된 도구와 연습 경로의 작업만 요청했습니다. 승인받을 수 없는 호출은 차단된 상태를 유지했고, 전체 권한 우회 모드는 사용하지 않았습니다.",
        "- Claude settings.json과 installed_plugins.json 해시는 각 실행 전후 모두 일치했습니다. 이 두 파일의 보존 검사이지 사용자 프로필 전체의 바이트 비교는 아닙니다.",
        "- 사용자 직접 시험용 바탕화면 workspace 원본을 사용하지 않고 별도 복사본에서 시험했습니다.", "",
        "## 시험별 결과", "", "| 시험 | 판정 | 실제 확인 |", "| --- | --- | --- |"]
    for case, (verdict, note) in VERDICTS.items():
        lines.append(f"| {case} | {verdict} | {note} |")
    lines += ["", "CLI가 반환한 success는 응답 생성이 끝났다는 뜻입니다. 업무 성공, 검증 로그 저장, 개인 기억 학습 성공을 의미하지 않습니다.", "",
        "## 추가로 실행한 코드 검사", "",
        "`test_work_milestones.py`, `test_memory.py`, `test_model_router.py`, `test_learning_lifecycle.py`: **65개 통과, 실패 0개, 제외 0개**, 약 12.9초.",
        "이 검사는 임시 파일과 테스트 입력으로 엔진을 확인한 것입니다. 실제 대화의 승인·명령 생성·UI까지 통과했다는 뜻은 아닙니다.", "",
        "## 수정 전에 구분해야 할 원인", "",
        "### 1. 테스트 실행기의 승인 조건과 하네스 완료 절차", "",
        "이번 무인 실행은 승인을 대신 누르지 않도록 설정했습니다. 허용 규칙의 정확한 경로/명령과 모델이 작성한 따옴표·짧은 실행 파일 이름·추가 `--` 등이 달라 일부 PowerShell 명령이 승인을 요구했습니다. 이 차단을 하네스의 저장 엔진 고장이라고 단정하면 안 됩니다.",
        "다만 승인 불가가 이미 알려진 뒤에도 Stop이 반복 보정을 요구해 사용자에게 내부 검증 보고가 길게 노출됐습니다. 지원된 명령을 일관되게 제공하고, 승인 불가 작업에는 보정 요청을 반복하지 않는 종료 처리가 필요합니다. 전체 Bash 자동 허용으로 해결하면 안 됩니다.", "",
        "### 2. 읽기 전용 파일 처리와 변경 판정", "",
        "EML 읽기에서 생성된 디코딩용 Bash 명령이 변경 가능 작업으로 잡혔습니다. 임의 코드를 무조건 읽기 전용으로 인정하는 대신, 파일 범위가 고정된 읽기 전용 파서/진단 경로를 제공하고 그 호출을 정확히 분류해야 합니다.", "",
        "### 3. 실행 근거에 맞는 안내", "",
        "- 실제로 거부된 search를 upsert 실패로 바꿔 설명하지 않아야 합니다.",
        "- memory search의 지원 문법은 `memory search <query>`입니다. 임의 `--query` 예시를 만들지 않도록 도움말/예시와 호출 검증을 보강해야 합니다.",
        "- Outlook 계정은 Outlook/MCP가 반환한 정보로만 확인합니다. Claude 로그인 계정으로 대체하지 않습니다.",
        "- 보호된 자료는 제외하고 필요한 경우 승인된 정상 절차의 담당자 확인만 안내합니다. 보호 해제를 일반적인 해결책으로 제안하지 않습니다.", "",
        "## 아직 판정하지 않은 기능", "",
        "개인 기억 저장 후 새 대화 회상, 업무 중간 후보→완료 후 학습→다음 업무 개선 효과, 개인 스킬 자동 개선, 실제 SMALL/MEDIUM/LARGE worker 실행, 네이티브 설치/업데이트, 파일 이동 승인창·되돌리기, 실제 HTML/PPT 완성물, Outlook/PST·사내 DB·DRM·이미지 모델 통합은 이번 실제 대화 검사에서 완료 판정하지 않았습니다.",
        "이번에는 검증과 증거 정리만 수행했습니다. 발견한 문제를 가리기 위해 제품 코드를 바꾸거나 성공 기록을 직접 넣지 않았습니다.", "",
        "## 실제 요청과 응답", "", "아래 이메일은 가렸습니다. 읽기 쉬운 결과서이며 원본 이벤트와 세션 기록은 로컬 개발 검증 폴더에 별도 보관했습니다."]
    for case in VERDICTS:
        s = by_case[case]
        evidence = Path(s["evidence"])
        request = json.loads((evidence / "request.json").read_text(encoding="utf-8"))
        lines += ["", f"### {case} · {VERDICTS[case][0]}", "",
            f"소요: {s['elapsedSeconds']}초 · 종료 코드: {s['exitCode']} · 제한시간 종료: {s['timeout']}", "",
            "요청:", "", "```text", clean(request["prompt"]), "```", "",
            "최종 응답:" if s.get("result") else "최종 완료 전 마지막 답변 (전체 실행 미완료):", ""]
        answer = s.get("result") or (s.get("assistantText") or ["응답 없음"])[-1]
        lines.extend("> " + line for line in clean(answer).splitlines())
        lines += ["", f"사용한 도구: {', '.join(s['tools']) or '도구 호출 없음'}", "",
                  f"[로컬 실행 증거]({evidence.as_posix()}/summary.json)"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = render(args.root)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(output)
    print(json.dumps({"report": str(args.output), "cases": len(VERDICTS)}, ensure_ascii=True))
