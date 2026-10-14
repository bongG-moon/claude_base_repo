import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import openpyxl
from openpyxl.workbook.defined_name import DefinedName

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import migration_contract as contract


class ContractTests(unittest.TestCase):
    def extraction(self):
        return {"status": "extracted", "modules": [
            {"name": "Module1", "relative_path": "modules/001_Module1.bas", "source": "Sub Run()\r\nEnd Sub\r\n"},
            {"name": "ThisWorkbook", "relative_path": "modules/002_ThisWorkbook.cls", "source": "Attribute VB_Name = \"ThisWorkbook\"\n"}]}

    def test_line_endings_are_normalized(self):
        a = self.extraction()
        b = copy.deepcopy(a)
        b["modules"][0]["source"] = b["modules"][0]["source"].replace("\r\n", "\n")
        self.assertEqual(contract.module_identity(a), contract.module_identity(b))

    def test_source_change_module_addition_deletion_all_detected(self):
        original = self.extraction()
        baseline = contract.module_identity(original)
        changed = copy.deepcopy(original)
        changed["modules"][0]["source"] += "' changed source\n"
        self.assertNotEqual(baseline, contract.module_identity(changed))
        changed = copy.deepcopy(original)
        changed["modules"].pop()
        self.assertNotEqual(baseline, contract.module_identity(changed))
        changed = copy.deepcopy(original)
        changed["modules"].append({"name": "NewEvent", "relative_path": "modules/003_Event.cls", "source": "Private Sub Workbook_Open()\nEnd Sub"})
        self.assertNotEqual(baseline, contract.module_identity(changed))

    def test_unavailable_source_does_not_match(self):
        for status in ("no_vba", "dependency_missing", "malformed", "timeout"):
            with self.subTest(status=status), self.assertRaises(contract.InputError):
                contract.module_identity({"status": status, "modules": []})

    def test_existing_contract_is_not_refreshed_to_match(self):
        baseline = {"version": 1, "headers": [], "modules": ["reviewed"], "formula_sha256": "before"}
        with tempfile.TemporaryDirectory(dir=SKILL / "tests") as temp:
            saved = Path(temp) / "contract.json"
            saved.write_text(json.dumps(baseline), encoding="utf-8")
            before = saved.read_bytes()
            with patch.object(contract, "observe_contract", return_value={**baseline, "formula_sha256": "after"}):
                with self.assertRaisesRegex(contract.InputError, "formula_sha256"):
                    contract.verify_contract("input.xlsm", saved)
            self.assertEqual(before, saved.read_bytes())

    def test_matching_contract_passes(self):
        baseline = {"version": 1, "headers": [], "modules": [], "formula_count": 2}
        with tempfile.TemporaryDirectory(dir=SKILL / "tests") as temp:
            saved = Path(temp) / "contract.json"
            saved.write_text(json.dumps(baseline), encoding="utf-8")
            with patch.object(contract, "observe_contract", return_value=baseline):
                self.assertEqual(contract.verify_contract("input.xlsm", saved)["status"], "matched")

    def test_sheet_scoped_name_changes_contract(self):
        # In-memory workbook isolates the contract behavior without authoring files.
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Inputs"
        sheet["A1"] = "=LocalRate"
        extraction = self.extraction()
        with tempfile.TemporaryDirectory(dir=SKILL / "tests") as temp:
            source = Path(temp) / "input.xlsm"
            source.write_bytes(b"contract fixture")
            import hashlib
            extraction["container_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch.object(contract, "preflight"), patch.object(contract.openpyxl, "load_workbook", return_value=workbook):
                sheet.defined_names.add(DefinedName("LocalRate", attr_text="Inputs!$B$1"))
                before = contract.observe_contract(source, [], extraction)
                sheet.defined_names.add(DefinedName("LocalRate", attr_text="Inputs!$B$2"))
                after = contract.observe_contract(source, [], extraction)
        self.assertNotEqual(before["defined_names"], after["defined_names"])


if __name__ == "__main__":
    unittest.main()
