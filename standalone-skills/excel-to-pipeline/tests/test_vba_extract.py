"""Static VBA container/extraction limits. No Excel or macro execution."""
import base64
import builtins
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vba_extract", ROOT / "scripts" / "vba_extract.py")
vba = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vba)


def package(*, target="vbaProject.bin", target_mode="Internal", has_vba=True, extra=None, root=None):
    entries = {
        "_rels/.rels": root or f'<Relationships xmlns="{vba.REL_NS}"><Relationship Id="r1" Type="{sorted(vba.OFFICE_REL)[0]}" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{vba.REL_NS}">' + (f'<Relationship Id="r2" Type="{vba.VBA_REL}" Target="{target}" TargetMode="{target_mode}"/>' if has_vba else '') + '</Relationships>',
    }
    if has_vba:
        entries["xl/vbaProject.bin"] = vba.OLE_MAGIC + bytes(504)
    if extra:
        entries.update(extra)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for name, value in entries.items():
            z.writestr(name, value)
    return output.getvalue()


def module(name="Test", source='Attribute VB_Name = "Test"\nSub Run()\nEnd Sub\n', index=1):
    encoded = source.encode("utf-8")
    return {"name": name, "relative_path": vba.module_path(index, name, "bas"), "source": source,
            "source_sha256": hashlib.sha256(encoded).hexdigest(), "stream_path": "VBA/Test"}


class ContainerTest(unittest.TestCase):
    def test_main_workbook_relationship_only_no_embedded_scan(self):
        data = package(extra={"xl/embeddings/other.xls": b"never open this", "other/vbaProject.bin": b"do not parse"})
        part, payload, workbook = vba.main_vba_part(data)
        self.assertEqual(part, "xl/vbaProject.bin")
        self.assertEqual(workbook, "xl/workbook.xml")
        self.assertEqual(payload, vba.OLE_MAGIC + bytes(504))

    def test_unconnected_macro_filename_is_not_a_project(self):
        data = package(has_vba=False, extra={"xl/vbaProject.bin": b"not authorized by relationship"})
        self.assertIsNone(vba.main_vba_part(data)[0])

    def test_non_default_part_name_is_selected(self):
        data = package(target="custom.bin", extra={"xl/custom.bin": vba.OLE_MAGIC + bytes(504)})
        self.assertEqual(vba.main_vba_part(data)[0], "xl/custom.bin")

    def test_external_relationship_is_rejected_without_access(self):
        with self.assertRaises(vba.ExtractionError) as err:
            vba.main_vba_part(package(target="https://example.invalid/source.bin", target_mode="External"))
        self.assertEqual(err.exception.status, "malformed")

    def test_bad_zip_member_paths_are_rejected(self):
        for path in ["../evil", "/absolute", "C:/evil", "xl/./bad", "xl/../bad"]:
            with self.subTest(path=path), self.assertRaises(vba.ExtractionError):
                vba.main_vba_part(package(extra={path: b"bad"}))
        # Windows ZipFile normalizes backslashes when writing; patch both header
        # names to test a genuinely malformed archive member instead.
        data = package(extra={"xl!bad": b"bad"}).replace(b"xl!bad", b"xl\\bad")
        with self.assertRaises(vba.ExtractionError):
            vba.main_vba_part(data)

    def test_relationship_traversal_and_encoded_nul_rejected(self):
        for target in ["../../evil", "%2e%2e/%2e%2e/evil", "vba%00.bin", "file:///C:/bad", "//server/a", "vba.bin#x"]:
            with self.subTest(target=target), self.assertRaises(vba.ExtractionError):
                vba.main_vba_part(package(target=target))

    def test_dtd_entity_rejected_including_utf16(self):
        text = f'<!DOCTYPE Relationships [<!ENTITY x "xl/workbook.xml">]><Relationships xmlns="{vba.REL_NS}"/>'
        for value in [text, text.encode("utf-16")]:
            with self.subTest(kind=type(value).__name__), self.assertRaises(vba.ExtractionError):
                vba.main_vba_part(package(root=value))

    def test_duplicate_zip_parts_rejected(self):
        raw = io.BytesIO(package())
        with zipfile.ZipFile(raw, "a") as z:
            z.writestr("xl/WORKBOOK.xml", b"ambiguous")
        with self.assertRaises(vba.ExtractionError):
            vba.main_vba_part(raw.getvalue())

    def test_wrong_ole_and_missing_target_rejected(self):
        for data in [package(extra={"xl/vbaProject.bin": b"bad"}), package(target="missing.bin")]:
            with self.assertRaises(vba.ExtractionError):
                vba.main_vba_part(data)

    def test_encrypted_or_legacy_container_not_called_malformed_vba(self):
        with self.assertRaises(vba.ExtractionError) as error:
            vba.main_vba_part(vba.OLE_MAGIC + bytes(504))
        self.assertEqual(error.exception.status, "encrypted_or_non_ooxml")

    def test_container_limits(self):
        with patch.object(vba, "MAX_CONTAINER", 20), self.assertRaises(vba.ExtractionError):
            vba.main_vba_part(package())
        with patch.object(vba, "MAX_VBA", 32), self.assertRaises(vba.ExtractionError):
            vba.main_vba_part(package())


class CompressionTest(unittest.TestCase):
    def test_literal_chunk_size_checked_without_decoding(self):
        self.assertEqual(vba.decompressed_size(b"\x01" + struct.pack("<H", 0xB003) + b"\x00abc"), 3)

    def test_uncompressed_chunk_exact_length(self):
        data = b"\x01" + struct.pack("<H", 0x3FFF) + bytes(4096)
        self.assertEqual(vba.decompressed_size(data), 4096)
        with self.assertRaises(vba.ExtractionError):
            vba.decompressed_size(data[:-1])

    def test_copy_token_cannot_reference_before_chunk(self):
        with self.assertRaises(vba.ExtractionError):
            vba.decompressed_size(b"\x01" + struct.pack("<H", 0xB002) + b"\x01\x00\x00")

    def test_invalid_signature_truncated_header_and_expansion_limit(self):
        for data in [b"", b"\x02", b"\x01\x00", b"\x01\x00\x00a"]:
            with self.subTest(data=data), self.assertRaises(vba.ExtractionError):
                vba.decompressed_size(data)
        with self.assertRaises(vba.ExtractionError) as err:
            vba.decompressed_size(b"\x01" + struct.pack("<H", 0xB003) + b"\x00abc", limit=2)
        self.assertEqual(err.exception.status, "limit_exceeded")


class WorkerTest(unittest.TestCase):
    def test_missing_dependency_is_explicit(self):
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == "oletools":
                raise ImportError("not installed")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", missing):
            self.assertEqual(vba.parse_project_bytes(b"unused")["status"], "dependency_missing")

    def test_timeout_kills_no_shell_worker(self):
        with patch.object(vba.subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 1)) as run:
            result = vba.run_worker(b"input", 1)
            self.assertEqual(result["status"], "timeout")
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs["input"], base64.b64encode(b"input"))

    def test_invalid_worker_output_rejected(self):
        with patch.object(vba.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout=b"not json")):
            self.assertEqual(vba.run_worker(b"x", 1)["status"], "worker_failed")

    def test_workbook_hash_preserved_and_no_macro_fast_path(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            source = Path(temp) / "source.xlsx"
            source.write_bytes(package(has_vba=False))
            before = source.read_bytes()
            with patch.object(vba, "run_worker") as worker:
                result = vba.extract_vba(source)
                worker.assert_not_called()
            self.assertEqual(result["status"], "no_vba")
            self.assertTrue(result["source_unchanged"])
            self.assertEqual(result["container_sha256"], hashlib.sha256(before).hexdigest())
            self.assertEqual(source.read_bytes(), before)

    def test_selected_part_only_sent_to_worker(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            source = Path(temp) / "source.xlsm"
            source.write_bytes(package())
            returned = vba.outcome("extracted")
            returned["modules"] = [module()]
            with patch.object(vba, "run_worker", return_value=returned) as worker:
                result = vba.extract_vba(source)
            self.assertEqual(worker.call_args.args[0], vba.OLE_MAGIC + bytes(504))
            self.assertEqual(result["vba_sha256"], hashlib.sha256(vba.OLE_MAGIC + bytes(504)).hexdigest())

    def test_invalid_timeout_is_rejected(self):
        for timeout in [0, -1, 121, float("inf"), float("nan")]:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                vba.extract_vba("does-not-matter.xlsm", timeout=timeout)


class PublishTest(unittest.TestCase):
    def test_safe_names_and_original_module_identity(self):
        safe = vba.module_path(1, "../CON:한국어", "frm")
        self.assertEqual(safe, "modules/001_CON_한국어.cls")

    def test_utf8_source_and_manifest_hash(self):
        result = vba.outcome("extracted")
        result["modules"] = [module(source="' 한국어\r\nSub Run()\r\nEnd Sub\r\n")]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            output = Path(temp) / "new"
            paths = vba.publish_sources(result, output)
            self.assertEqual(paths[0].read_bytes().decode("utf-8"), result["modules"][0]["source"])
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("source", manifest["modules"][0])
            with self.assertRaises(ValueError):
                vba.publish_sources(result, output)

    def test_no_vba_and_failed_manifest_only(self):
        for status in ["no_vba", "malformed", "dependency_missing"]:
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
                output = Path(temp) / "new"
                self.assertEqual(vba.publish_sources(vba.outcome(status), output), [])
                self.assertEqual([p.name for p in output.iterdir()], ["manifest.json"])

    def test_publish_rejects_traversal_hash_mismatch_and_partial_sources(self):
        for change in [{"relative_path": "../evil.bas"}, {"source_sha256": "wrong"}]:
            result = vba.outcome("extracted")
            result["modules"] = [dict(module(), **change)]
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp, self.assertRaises(ValueError):
                vba.publish_sources(result, Path(temp) / "new")
        result = vba.outcome("malformed")
        result["modules"] = [module()]
        with self.assertRaises(ValueError):
            vba.publish_sources(result, "unused")


if __name__ == "__main__":
    unittest.main()
