"""Bounded arithmetic and reusable report numbers; no eval, files or model calls.

Only declared bindings/checks are verified. Free prose and source authenticity
are deliberately not marked verified by this module.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any


class FactError(ValueError):
    pass


def number(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise FactError("계산에는 숫자만 사용해 주세요.")
    if isinstance(value, str) and not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value.strip()):
        raise FactError("계산 대상 셀에는 단위나 쉼표 없이 숫자를 넣어 주세요.")
    try:
        result = Decimal(str(value).strip())
    except InvalidOperation:
        raise FactError("계산에 사용할 수 없는 숫자입니다.") from None
    if not result.is_finite() or abs(result) > Decimal("1e15"):
        raise FactError("계산 숫자의 범위를 확인해 주세요.")
    return result


def resolve(spec: dict, sections: list[dict]) -> tuple[dict, dict]:
    raw = spec.get("facts", [])
    if not isinstance(raw, list) or len(raw) > 128:
        raise FactError("공통 수치는 128개 이하로 지정해 주세요.")
    facts: dict[str, dict] = {}

    def operand(value):
        if not isinstance(value, dict):
            return number(value)
        if set(value) == {"fact"}:
            key = value["fact"]
            if not isinstance(key, str) or key not in facts:
                raise FactError("수치 참조는 먼저 정의된 공통 수치만 사용할 수 있습니다.")
            return facts[key]["number"]
        if len(value) != 1 or next(iter(value)) not in {"table", "chart"}:
            raise FactError("표 또는 차트의 셀 위치로 수치를 참조해 주세요.")
        kind, pos = next(iter(value.items()))
        if not isinstance(pos, list) or len(pos) != 3 or any(type(i) is not int or i < 0 for i in pos):
            raise FactError("셀 참조에는 0부터 시작하는 위치 3개가 필요합니다.")
        try:
            section = sections[pos[0]]
            cell = section[kind]["rows"][pos[1]][pos[2]] if kind == "table" else section[kind]["series"][pos[1]]["values"][pos[2]]
        except (IndexError, KeyError, TypeError):
            raise FactError("계산에 참조한 표/차트 셀을 찾을 수 없습니다.") from None
        return number(cell)

    for row in raw:
        if not isinstance(row, dict):
            raise FactError("공통 수치의 형식을 확인해 주세요.")
        key = row.get("id")
        if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", key) or key in facts:
            raise FactError("공통 수치 ID는 중복 없는 영문 이름이어야 합니다.")
        inputs = row.get("inputs", [])
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= 7200:
            raise FactError("계산 입력 개수를 확인해 주세요.")
        values = [operand(v) for v in inputs]
        op = row.get("op", "sum")
        if op == "sum":
            calculated = sum(values, Decimal(0))
        elif op == "value" and len(values) == 1:
            calculated = values[0]
        elif op in ("ratio", "difference", "percent_change") and len(values) == 2:
            left, right = values
            if op == "difference":
                calculated = left - right
            elif right == 0:
                raise FactError("분모가 0인 비율은 계산할 수 없습니다. 확인 필요로 표시해 주세요.")
            else:
                calculated = (left / right if op == "ratio" else (left - right) / right) * 100
        else:
            raise FactError("지원하는 계산식과 입력 개수를 확인해 주세요.")
        calculated = number(calculated)
        digits = row.get("decimals", 0)
        if type(digits) is not int or not 0 <= digits <= 6:
            raise FactError("표시할 소수 자릿수는 0~6 사이여야 합니다.")
        quantum = Decimal(1).scaleb(-digits)
        rounded = calculated.quantize(quantum, rounding=ROUND_HALF_UP)
        if "expected" in row and number(row["expected"]).quantize(quantum, rounding=ROUND_HALF_UP) != rounded:
            raise FactError(f"공통 수치 {key}의 기대값과 실제 계산이 다릅니다. 요약과 원자료를 확인해 주세요.")
        label, unit = row.get("label", key), row.get("unit", "")
        if not isinstance(label, str) or len(label) > 200 or not isinstance(unit, str) or len(unit) > 30:
            raise FactError("지표 이름과 단위를 짧은 글자로 지정해 주세요.")
        facts[key] = {"number": calculated, "display": f"{rounded:,.{digits}f}", "label": label, "unit": unit}
    checks = spec.get("checks", [])
    if not isinstance(checks, list) or len(checks) > 128:
        raise FactError("수치 대조 항목은 128개 이하로 지정해 주세요.")
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("left"), str) or not isinstance(check.get("right"), str) or check["left"] not in facts or check["right"] not in facts:
            raise FactError("대조할 공통 수치를 찾을 수 없습니다.")
        if facts[check["left"]]["number"] != facts[check["right"]]["number"]:
            raise FactError("표·차트·총계의 수치가 일치하지 않습니다. 결과물을 만들기 전에 수정해 주세요.")
    return facts, {"arithmetic": "checked" if facts else "not_provided", "facts": len(facts), "crossChecks": len(checks),
                   "sourceAccuracy": "not_verified", "freeTextClaims": "not_verified", "visual": "not_verified"}


def bind(text: str, facts: dict) -> str:
    def replace(match):
        key = match.group(1)
        if key not in facts:
            raise FactError("본문이 참조한 공통 수치를 찾을 수 없습니다.")
        return facts[key]["display"]
    result = re.sub(r"\{\{fact:([a-zA-Z][a-zA-Z0-9_-]{0,63})\}\}", replace, text)
    if "{{fact:" in result:
        raise FactError("본문 수치 참조 형식을 확인해 주세요.")
    return result
