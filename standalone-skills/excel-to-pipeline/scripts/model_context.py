"""Bounded, model-facing evidence from a full local Excel analysis.

This module neither reads workbooks nor calls a model. The full analysis and
deterministic processing remain the source of truth. The output is intentionally
incomplete, and its budget counts serialized JSON characters, not model tokens.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

MAX_SAMPLE_ROWS = 1000
MIN_CONTEXT_CHARS = 1024
_REFERENCE = re.compile(r"(?<![\w.])(?P<col>\$?[A-Za-z]{1,3})(?P<absolute>\$?)(?P<row>[1-9]\d*)(?![\w.!(])")


def serialize_model_context(context):
    """The only serialization covered by limits.max_chars/serialized_chars."""
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _text(value, limit=120):
    value = str(value)
    if len(value) <= limit:
        return value
    return {"text": value[:limit], "original_chars": len(value), "truncated": True}


def _value(value):
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"unavailable": "non_finite_number"}
    return _text(value, 160)


def _truncations(value):
    if isinstance(value, dict):
        return int(value.get("truncated") is True and "original_chars" in value) + sum(
            _truncations(child) for key, child in value.items() if key != "truncated_fields")
    if isinstance(value, list):
        return sum(map(_truncations, value))
    return 0


def _row_pattern(formula, origin):
    """Preserve reference offsets and literals; still not semantic equivalence."""
    address = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?([1-9]\d*)", str(origin))
    if not address:
        return formula
    col = 0
    for letter in address[1].upper():
        col = col * 26 + ord(letter) - ord("A") + 1
    row = int(address[2])
    if col > 16384 or row > 1048576:
        return formula
    # Excel double-quoted strings and single-quoted sheet/workbook identifiers
    # are both literal. Escaped quotes remain intact, e.g. 'A1''s'!B2.
    parts = re.split(r'''("(?:[^"]|"")*"|'(?:[^']|'')*')''', formula)
    for index in range(0, len(parts), 2):
        parts[index] = _REFERENCE.sub(
            lambda match: match.group(0) if match["absolute"] else
            match["col"] + "[r" + format(int(match["row"]) - row, "+d") + "]", parts[index])
    return "".join(parts)


def _formula_groups(formulas):
    groups = {}
    for formula in formulas:
        expression = str(formula.get("formula", ""))
        pattern = _row_pattern(expression, formula.get("cell"))
        key = (str(formula.get("sheet", "")), str(formula.get("status", "unknown")),
               hashlib.sha256(pattern.encode("utf-8")).digest())
        if key not in groups:
            functions = formula.get("functions") or []
            groups[key] = {"sheet": _text(formula.get("sheet", "")),
                           "pattern": _text(pattern, 360), "count": 0,
                           "example": {"cell": _text(formula.get("cell", ""), 32),
                                       "formula": _text(expression, 480),
                                       "status": _text(formula.get("status", "unknown"), 48),
                                       "functions": [_text(f, 48) for f in functions[:8]],
                                       "omitted_functions": max(0, len(functions) - 8)}}
        groups[key]["count"] += 1
    return list(groups.values())


def build_model_context(result, sample_rows=5, max_chars=12000):
    """Return valid JSON evidence within max_chars when using the serializer.

    sample_rows selects at most the first N data rows of each table. Aggregate
    and repeated-header candidates are not samples. 1000 is a hard per-table
    ceiling, not a default. Smaller budgets omit whole entries, never slice JSON.
    Long text is a marked prefix, and row values correspond to shown columns.
    """
    if isinstance(sample_rows, bool) or not isinstance(sample_rows, int) or sample_rows < 0:
        raise ValueError("sample_rows must be a non-negative integer")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < MIN_CONTEXT_CHARS:
        raise ValueError(f"max_chars must be an integer of at least {MIN_CONTEXT_CHARS}")
    if not isinstance(result, dict):
        raise ValueError("result must be an Excel analysis dictionary")
    limit = min(sample_rows, MAX_SAMPLE_ROWS)
    sheets, tables, formulas = (result.get(name) or [] for name in ("sheets", "tables", "formulas"))
    extraction = result.get("vba") or {}
    indexed_modules = (result.get("vba_index") or {}).get("modules") or []
    modules = extraction.get("modules") or []
    procedures = [(module.get("file", ""), procedure) for module in indexed_modules
                  for procedure in module.get("procedures", [])]
    grouped = _formula_groups(formulas)
    # Build only short row indexes, not copies of full tables. Count all rows so
    # omissions stay explicit even when none of a table fits the global budget.
    table_info = []
    for table in tables:
        rows, kinds = table.get("rows") or [], table.get("row_kinds") or []
        eligible, selected = 0, []
        for index in range(len(rows)):
            if index < len(kinds) and kinds[index] != "data":
                continue
            eligible += 1
            if len(selected) < limit:
                selected.append(index)
        table_info.append({"table": table, "eligible": eligible, "selected": selected})
    totals = {"sheets": len(sheets), "tables": len(tables),
              "extracted_rows": sum(len(t.get("rows") or []) for t in tables),
              "data_rows": sum(info["eligible"] for info in table_info),
              "source_cells": len(result.get("source_cells") or []), "formulas": len(formulas),
              "formula_patterns": len(grouped), "vba_modules": len(modules), "vba_procedures": len(procedures)}
    context = {"version": 1, "kind": "excel_model_context", "scope": "partial_evidence_not_full_validation",
               "unit": "serialized_json_characters_not_tokens",
               "limits": {"requested_rows": sample_rows, "effective_rows": limit,
                          "hard_row_cap": MAX_SAMPLE_ROWS, "max_chars": max_chars},
               "totals": totals, "omitted": {}, "sampled_data_rows": 0,
               "truncated_fields": 0, "serialized_chars": 0,
               "sheets": [], "tables": [], "formula_patterns": [],
               "vba": {"status": _text(extraction.get("status", "not_present"), 48),
                       "modules": [], "procedures": []}}
    if (result.get("summary") or {}).get("reader") == "xlwings":
        # Keep the limitation even when a tiny budget drops source/row details.
        context["input"] = {"reader": "xlwings", "fresh_recalculation": False,
                            "metadata_incomplete": bool((result.get("input_evidence") or {}).get("incomplete_metadata"))}
    shown = []

    def refresh():
        sampled = sum(len(table["sample_rows"]) for table in context["tables"])
        context["sampled_data_rows"] = sampled
        context["omitted"] = {
            "sheets": totals["sheets"] - len(context["sheets"]),
            "tables": totals["tables"] - len(context["tables"]),
            "data_rows": totals["data_rows"] - sampled,
            "source_cells": totals["source_cells"],  # source-cell dump is intentionally absent
            "formula_patterns": totals["formula_patterns"] - len(context["formula_patterns"]),
            "formula_details": totals["formulas"] - len(context["formula_patterns"]),
            "vba_modules": totals["vba_modules"] - len(context["vba"]["modules"]),
            "vba_procedures": totals["vba_procedures"] - len(context["vba"]["procedures"]),
        }
        for table in context["tables"]:
            table["omitted_columns"] = table["column_count"] - len(table["columns"])
            table["omitted_data_rows"] = table["data_row_count"] - len(table["sample_rows"])
        context["truncated_fields"] = _truncations(context)
        # Fixed point includes the character count's own decimal digits.
        for _ in range(8):
            actual = len(serialize_model_context(context))
            if actual == context["serialized_chars"]:
                return actual
            context["serialized_chars"] = actual
        raise AssertionError("serialized character count did not converge")

    if refresh() > max_chars:
        raise ValueError("max_chars is too small for required counts and limits metadata")

    def append(destination, item, ceiling=None):
        destination.append(item)
        if refresh() <= (max_chars if ceiling is None else max(ceiling, MIN_CONTEXT_CHARS)):
            return True
        destination.pop()
        refresh()
        return False

    summary = result.get("summary") or {}
    flags = summary.get("review_flags") or []
    context["source"] = {"name": _text(summary.get("source_name", ""), 120),
                         "status": _text(summary.get("status", "unknown"), 48),
                         "review_flags": [_text(flag, 80) for flag in flags[:8]],
                         "omitted_review_flags": max(0, len(flags) - 8)}
    if summary.get("reader"):
        context["source"]["reader"] = summary["reader"]
        context["source"]["values_origin"] = summary.get("values_origin", "unknown")
    if refresh() > max_chars:
        del context["source"]
        refresh()
    # Structure and indexes have first priority, but do not consume the entire
    # budget before any evidence rows can be seen. Unused space is reused below.
    has_samples = limit > 0 and totals["data_rows"] > 0
    evidence_ceiling = int(max_chars * (0.8 if has_samples else 1))
    structure_ceiling = int(max_chars * (0.6 if formulas or modules else 0.8))
    pending_sheets, pending_tables = [], []
    # Tables include their own sheet/range; a tiny budget must not be filled
    # entirely with sheet names before a single useful table is represented.
    for info in table_info:
        table = info["table"]
        item = {"id": _text(table.get("id", ""), 64), "sheet": _text(table.get("sheet", "")),
                "range": _text(table.get("range", ""), 64),
                "extracted_row_count": len(table.get("rows") or []), "data_row_count": info["eligible"],
                "column_count": len(table.get("columns") or []),
                "columns": [{"index": index, "name": _text(name, 100)}
                            for index, name in enumerate((table.get("columns") or [])[:2])],
                "sample_rows": [],
                "omitted_columns": 0, "omitted_data_rows": 0}
        if append(context["tables"], item, structure_ceiling):
            shown.append((item, info))
        else:
            pending_tables.append((item, info))
    for sheet in sheets:
        item = {"name": _text(sheet.get("name", "")), "range": _text(sheet.get("range", ""), 64),
                "state": _text(sheet.get("state", "unknown"), 24), "table_count": sheet.get("table_count", 0)}
        if not append(context["sheets"], item, structure_ceiling):
            pending_sheets.append(item)

    def fill_columns(ceiling=None):
        for item, info in shown:
            columns = info["table"].get("columns") or []
            for index in range(len(item["columns"]), len(columns)):
                if not append(item["columns"], {"index": index, "name": _text(columns[index], 100)}, ceiling):
                    break

    fill_columns(structure_ceiling)
    # Non-computed patterns appear first; only one example per lexical pattern.
    grouped.sort(key=lambda group: group["example"]["status"] == "computed")
    pending_formulas = []
    for group in grouped:
        if not append(context["formula_patterns"], group,
                      min(evidence_ceiling, int(max_chars * (0.68 if modules else 0.8)))):
            pending_formulas.append(group)
    # Empty workbook/sheet classes are still counted, but useful procedure
    # modules precede them in a short model-facing index.
    active_files = {str(module.get("file", "")) for module in indexed_modules if module.get("procedures")}
    active_modules, empty_modules = [], []
    for module in modules:
        item = {"name": _text(module.get("name", ""), 100),
                "path": _text(module.get("relative_path", ""), 160),
                "type": _text(module.get("module_type", "unknown"), 32)}
        file = str(module.get("relative_path", "")).replace("\\", "/").rsplit("/", 1)[-1]
        (active_modules if file in active_files else empty_modules).append(item)
    pending_modules, pending_procedures = [], []
    for item in active_modules:
        if not append(context["vba"]["modules"], item, evidence_ceiling):
            pending_modules.append(item)
    for file, procedure in procedures:
        item = {"module": _text(file, 160), "name": _text(procedure.get("name", ""), 100),
                "kind": _text(procedure.get("kind", ""), 32),
                "start_line": procedure.get("start_line"), "end_line": procedure.get("end_line"),
                "event_candidate": bool(procedure.get("event_entry_candidate", False))}
        if not append(context["vba"]["procedures"], item, evidence_ceiling):
            pending_procedures.append(item)
    for item in empty_modules:
        if not append(context["vba"]["modules"], item, evidence_ceiling):
            pending_modules.append(item)
    # Spend unneeded reserved space on structure before sampling any cell values.
    for item in pending_sheets:
        if not append(context["sheets"], item, evidence_ceiling):
            break
    for item, info in pending_tables:
        if not append(context["tables"], item, evidence_ceiling):
            break
        shown.append((item, info))
    fill_columns(evidence_ceiling)
    # Round-robin gives each represented table a first data row before second rows.
    exhausted = set()
    for ordinal in range(limit):
        any_added = False
        for table_index, (item, info) in enumerate(shown):
            if table_index in exhausted or ordinal >= len(info["selected"]) or not item["columns"]:
                continue
            row_index = info["selected"][ordinal]
            table = info["table"]
            raw_row = table["rows"][row_index]
            source_rows = table.get("source_rows") or []
            sample = {"extracted_index": row_index,
                      "source_row": source_rows[row_index] if row_index < len(source_rows) else None,
                      "values": [_value(raw_row[column["index"]]) if column["index"] < len(raw_row) else None
                                 for column in item["columns"]]}
            if append(item["sample_rows"], sample):
                any_added = True
            else:
                # Never skip a large earlier row and present a later one as head.
                exhausted.add(table_index)
        if not any_added:
            break
    # When five rows are already enough, remaining space can improve the index.
    for destination, pending in ((context["vba"]["procedures"], pending_procedures),
                                 (context["vba"]["modules"], pending_modules),
                                 (context["formula_patterns"], pending_formulas)):
        for item in pending:
            if not append(destination, item):
                break
    assert refresh() <= max_chars
    return context
