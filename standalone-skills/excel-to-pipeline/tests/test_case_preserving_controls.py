"""Shared independent fixture oracle for tests of the user's case-preserving rule.

The workbook, embedded VBA and old manifest stay unchanged. Inspection confirms
EX000007 is the only old accepted row whose raw course code is ` c03 ` while
the reference table contains only `C03`. Case-sensitive matching now rejects it.
This helper never calls the production migration or generates its own expected
values from actual output.
"""
import copy


def revised_expected(original):
    expected = copy.deepcopy(original)
    affected = [row for row in expected["records"] if row["application_id"] == "EX000007"]
    if not affected:
        return expected  # Base input contains no exception rows.
    assert len(affected) == 1
    record = affected[0]
    assert record["source_sheet"] == "예외신청" and record["source_row"] == 15
    assert record["amount"] == 243013 and not record["completed"]
    expected["records"].remove(record)
    expected["approved_count"] -= 1
    expected["rejected_count"] += 1
    expected["total_amount"] -= 243013
    expected["rejected"].append({"application_id": "EX000007", "reason": "case_sensitive_course_mismatch"})
    department = next(row for row in expected["departments"] if row["department"] == "생산")
    department["approved_count"] -= 1
    department["total_amount"] -= 243013
    return expected
