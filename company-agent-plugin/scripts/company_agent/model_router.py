"""Deterministic, privacy-preserving model-tier routing for Company Agent.

The router examines the current prompt in memory and returns only a compact
decision. It performs no file, network, transcript, or telemetry I/O.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Final, Iterable


SMALL: Final = "SMALL"
MEDIUM: Final = "MEDIUM"
LARGE: Final = "LARGE"

MODEL_ALIAS: Final = {
    SMALL: "haiku",
    MEDIUM: "sonnet",
    LARGE: "opus",
}

AGENT_NAME: Final = {
    SMALL: "company-agent:small-worker",
    MEDIUM: "company-agent:medium-worker",
    LARGE: "company-agent:large-worker",
}

_MAX_CLASSIFIED_CHARS: Final = 100_000


@dataclass(frozen=True)
class RouteDecision:
    """Safe-to-inject routing metadata; never contains user prompt text."""

    tier: str
    model_alias: str
    agent: str
    verification_required: bool
    reason_codes: tuple[str, ...]
    schema_version: int = 1

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["reason_codes"] = list(self.reason_codes)
        return value

    def as_additional_context(
        self,
        *,
        session_id: str | None = None,
        personal_memory_context: str | None = None,
    ) -> str:
        envelope = {
            "company_agent_route": self.as_dict(),
            "company_agent_instruction": (
                f"For this turn, use {self.agent} as the primary execution worker. "
                "Keep the parent conversation as coordinator, apply managed policy and effective knowledge, "
                "and verify durable changes before reporting completion. If company_agent_session_id is present, "
                "use that exact sanitized identifier when recording verification."
            ),
        }
        if session_id:
            envelope["company_agent_session_id"] = session_id
        if personal_memory_context:
            envelope["company_agent_personal_memory_context"] = personal_memory_context
        return json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


_LARGE_PATTERNS: Final = (
    # Cross-system design and broad change
    r"\b(system|solution|enterprise|platform)\s+architecture\b",
    r"\b(cross[- ]system|multi[- ]system|organization[- ]wide|company[- ]wide)\b",
    r"\b(large[- ]scale|major)\s+(migration|refactor|redesign)\b",
    r"전사\s*(아키텍처|구조|설계|배포|마이그레이션)",
    r"(시스템|솔루션|플랫폼)\s*(아키텍처|전면\s*개편|재설계)",
    r"(대규모|전체)\s*(마이그레이션|리팩터링|재설계)",
    # High consequence or hard diagnosis
    r"\b(security[- ]critical|threat model|incident response|data loss|root cause)\b",
    r"\b(authentication|authorization)\s+(architecture|redesign|migration)\b",
    r"(보안|권한|인증|인가)\s*(아키텍처|위협\s*모델|전면\s*개편)",
    r"(장애|사고)(?:의)?\s*(근본\s*원인|원인\s*분석|대응)",
    # Reusable agent assets need stronger reasoning and review
    r"\b(create|build|design|implement|generate)\b.{0,50}\b(mcp server|agent harness|skill registry)\b",
    r"\b(self[- ]feedback|self[- ]evolution|agent architecture)\b",
    r"(mcp|스킬|skill|툴|tool)\s*(서버|레지스트리)?\s*(생성|제작|구현|설계)",
    r"(자가\s*피드백|자가\s*진화|에이전트)\s*(하네스|아키텍처|구조)\s*(구현|설계|구축)?",
)

_MEDIUM_PATTERNS: Final = (
    r"\b(implement|debug|diagnose|fix|refactor|test|analy[sz]e|investigate)\b",
    r"\b(create|write|update|modify)\b.{0,40}\b(code|script|file|document|report|query)\b",
    r"\b(sql|database|outlook|email|spreadsheet|api|mcp)\b",
    r"(구현|디버그|진단|수정|리팩터링|테스트|분석|조사)",
    r"(코드|스크립트|파일|문서|보고서|쿼리|메일)\s*(작성|생성|수정|실행|발송)",
    r"(데이터베이스|테이블|아웃룩|엑셀|api|mcp)",
)

_SMALL_PATTERNS: Final = (
    r"\b(summarize|translate|reformat|format|rename|explain briefly|quick lookup)\b",
    r"\b(fix|correct)\s+(a\s+)?(typo|spelling|formatting)\b",
    r"(짧게|간단히)\s*(설명|요약|정리|번역)",
    r"(요약|번역|서식\s*정리|오탈자\s*수정|맞춤법\s*수정)",
    r"(단순|간단한)\s*(조회|변경|질문)",
)

_WRITE_PATTERNS: Final = (
    r"\b(create|write|edit|update|modify|delete|rename|move|refactor|implement|fix|patch)\b.{0,60}\b(file|code|script|module|document|config|test|project|repo)\b",
    r"\b(apply|make|commit)\b.{0,30}\b(change|changes|patch|edit|commit)\b",
    r"(파일|코드|스크립트|모듈|문서|설정|테스트|프로젝트|레포|저장소).{0,80}(생성|작성|편집|수정|삭제|이름\s*변경|이동|리팩터링|구현|패치)",
    r"(변경|수정|구현|패치)\s*(해줘|해주세요|진행|적용)",
)

_EXPLICIT_LARGE: Final = (
    r"\b(use|route|switch to)\s+(the\s+)?large(\s+model)?\b",
    r"\bhighest[- ]capability model\b",
    r"(large|라지|대형|고성능)\s*(모델)?\s*(로|으로)?\s*(사용|전환|처리|해줘)",
)

_EXPLICIT_MEDIUM: Final = (
    r"\b(use|route|switch to)\s+(the\s+)?medium(\s+model)?\b",
    r"(medium|미디엄|중형)\s*(모델)?\s*(로|으로)?\s*(사용|전환|처리|해줘)",
)

_EXPLICIT_SMALL: Final = (
    r"\b(use|route|switch to)\s+(the\s+)?small(\s+model)?\b",
    r"\bsmall\s*(?:model|모델)",
    r"(small|스몰|소형)\s*(모델)?\s*(로|으로)?\s*(사용|전환|처리|해줘)",
)


def _matches_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in patterns)


def _count_distinct(text: str, words: Iterable[str]) -> int:
    return sum(1 for word in words if word in text)


def classify_prompt(prompt: str) -> RouteDecision:
    """Classify one prompt without retaining or returning its content.

    Routing is deliberately conservative: MEDIUM is the default, LARGE safety
    signals override any request to use a smaller tier, and SMALL is selected
    only for clearly bounded work.
    """

    text = (prompt or "")[:_MAX_CLASSIFIED_CHARS].casefold()
    reason_codes: list[str] = []

    large_signal = _matches_any(text, _LARGE_PATTERNS)
    medium_signal = _matches_any(text, _MEDIUM_PATTERNS)
    small_signal = _matches_any(text, _SMALL_PATTERNS)

    explicit_large = _matches_any(text, _EXPLICIT_LARGE)
    explicit_medium = _matches_any(text, _EXPLICIT_MEDIUM)
    explicit_small = _matches_any(text, _EXPLICIT_SMALL)

    if len(text) >= 5_000:
        large_signal = True
        reason_codes.append("LONG_PROMPT")
    elif len(text) >= 1_500:
        medium_signal = True
        reason_codes.append("NONTRIVIAL_PROMPT")

    system_terms = (
        "database",
        "outlook",
        "api",
        "mcp",
        "deployment",
        "security",
        "데이터베이스",
        "아웃룩",
        "배포",
        "보안",
    )
    if _count_distinct(text, system_terms) >= 3:
        large_signal = True
        reason_codes.append("CROSS_SYSTEM_SCOPE")

    if explicit_large:
        tier = LARGE
        reason_codes.append("EXPLICIT_LARGE")
    elif large_signal:
        tier = LARGE
        reason_codes.append("HIGH_COMPLEXITY_OR_RISK")
        if explicit_small or explicit_medium:
            reason_codes.append("SAFE_TIER_FLOOR_APPLIED")
    elif explicit_medium:
        tier = MEDIUM
        reason_codes.append("EXPLICIT_MEDIUM")
    elif explicit_small and not medium_signal:
        tier = SMALL
        reason_codes.append("EXPLICIT_SMALL")
    elif medium_signal:
        tier = MEDIUM
        reason_codes.append("MULTISTEP_OR_TOOL_WORK")
    elif small_signal:
        tier = SMALL
        reason_codes.append("BOUNDED_LOW_RISK_TASK")
    else:
        tier = MEDIUM
        reason_codes.append("CONSERVATIVE_DEFAULT")

    verification_required = _matches_any(text, _WRITE_PATTERNS)
    if verification_required:
        reason_codes.append("FILE_WRITE_INTENT")

    # Preserve insertion order while making repeated signals deterministic.
    unique_reasons = tuple(dict.fromkeys(reason_codes))
    return RouteDecision(
        tier=tier,
        model_alias=MODEL_ALIAS[tier],
        agent=AGENT_NAME[tier],
        verification_required=verification_required,
        reason_codes=unique_reasons,
    )


def hook_output(
    decision: RouteDecision,
    *,
    session_id: str | None = None,
    personal_memory_context: str | None = None,
) -> dict[str, object]:
    """Build the only stdout object emitted by the UserPromptSubmit hook."""

    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": decision.as_additional_context(
                session_id=session_id,
                personal_memory_context=personal_memory_context,
            ),
        }
    }
