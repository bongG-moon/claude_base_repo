from __future__ import annotations

from email.message import EmailMessage
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent import business_eml as eml


class LocalEmlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def mail(self, message: EmailMessage):
        file = self.root / "가상 메일 — sample.eml"
        file.write_bytes(message.as_bytes())
        return file

    def sample(self):
        message = EmailMessage()
        message["Subject"] = "가상 일정"
        message["From"] = "synthetic@example.test"
        message.set_content("회의는 내일 오후 2시입니다.")
        return message

    def test_plain_body_and_txt_attachment_preserve_source(self):
        message = self.sample()
        message.add_attachment("14:30 가상 검토", subtype="plain", filename="일정.txt")
        file = self.mail(message)
        before = hashlib.sha256(file.read_bytes()).hexdigest()
        result = eml.read_eml(file)
        self.assertEqual("ok", result["status"])
        self.assertIn("오후 2시", result["body"])
        self.assertEqual("read", result["attachments"][0]["status"])
        self.assertIn("14:30", result["attachments"][0]["content"])
        self.assertEqual(before, hashlib.sha256(file.read_bytes()).hexdigest())
        self.assertEqual([file], list(self.root.iterdir()))
        self.assertFalse(result["outlook_connected"])
        self.assertFalse(result["rawContentStored"])

    def test_missing_charset_reads_strict_utf8_body_and_attachment(self):
        for text in ("ASCII schedule 14:30", "14:30 가상 검토"):
            with self.subTest(text=text):
                message = EmailMessage()
                message.set_content(text.encode("utf-8"), maintype="text", subtype="plain")
                message.add_attachment(text.encode("utf-8"), maintype="text", subtype="plain", filename="일정.txt")
                body, attachment = list(message.iter_parts())
                self.assertIsNone(body.get_content_charset())
                self.assertIsNone(attachment.get_content_charset())
                file = self.mail(message)
                original = file.read_bytes()
                result = eml.read_eml(file)
                self.assertEqual("ok", result["status"])
                self.assertTrue(result["body_read"])
                self.assertEqual(text, result["body"])
                self.assertEqual("read", result["attachments"][0]["status"])
                self.assertEqual(text, result["attachments"][0]["content"])
                self.assertEqual([], result["partial_reasons"])
                self.assertEqual(original, file.read_bytes())
                self.assertEqual([file], list(self.root.iterdir()))

    def test_declared_legacy_charset_is_honored(self):
        message = self.sample()
        text = "14:30 가상 검토"
        message.add_attachment(text.encode("cp949"), maintype="text", subtype="plain", filename="일정.txt")
        next(message.iter_attachments()).set_param("charset", "cp949")
        result = eml.read_eml(self.mail(message))
        self.assertEqual("ok", result["status"])
        self.assertEqual(text, result["attachments"][0]["content"])

    def test_bad_attachment_encoding_is_excluded_without_losing_body(self):
        cases = (
            (None, b"SECRET\xff"),
            ("utf-8", b"SECRET\xff"),
            ("ascii", "SECRET 가상".encode("utf-8")),
            ("x-unknown-charset", b"SECRET"),
            ("", b"SECRET"),
        )
        for charset, payload in cases:
            with self.subTest(charset=charset):
                message = self.sample()
                message.add_attachment(payload, maintype="text", subtype="plain", filename="일정.txt")
                if charset is not None:
                    next(message.iter_attachments()).set_param("charset", charset)
                file = self.mail(message)
                original = file.read_bytes()
                result = eml.read_eml(file)
                self.assertEqual("partial", result["status"])
                self.assertTrue(result["body_read"])
                self.assertIn("오후 2시", result["body"])
                attachment = result["attachments"][0]
                self.assertEqual("excluded", attachment["status"])
                self.assertEqual("part_decode_failed", attachment["code"])
                self.assertNotIn("content", attachment)
                self.assertIn("인코딩", attachment["message"])
                self.assertIn("일부만", result["message"])
                self.assertNotIn("SECRET", str(result))
                self.assertNotIn("\ufffd", str(result))
                self.assertEqual(original, file.read_bytes())

    def test_bad_body_encoding_does_not_hide_readable_attachment(self):
        for charset in (None, "utf-8", "x-unknown-charset", ""):
            with self.subTest(charset=charset):
                message = EmailMessage()
                message.set_content(b"SECRET\xff", maintype="text", subtype="plain")
                if charset is not None:
                    message.set_param("charset", charset)
                message.add_attachment("14:30 가상 검토", subtype="plain", filename="일정.txt")
                result = eml.read_eml(self.mail(message))
                self.assertEqual("partial", result["status"])
                self.assertFalse(result["body_read"])
                self.assertEqual("", result["body"])
                self.assertEqual("read", result["attachments"][0]["status"])
                self.assertIn("14:30 가상 검토", result["attachments"][0]["content"])
                self.assertIn("part_decode_failed", result["partial_reasons"])
                self.assertIn("일반 텍스트 본문은 읽지 못했습니다", result["message"])
                self.assertIn("일부만", result["message"])
                self.assertNotIn("SECRET", str(result))

    def test_html_urls_are_not_rendered_or_fetched(self):
        message = EmailMessage()
        message.set_content('<script>fetch("https://example.test/secret")</script>', subtype="html")
        result = eml.read_eml(self.mail(message))
        self.assertFalse(result["body_read"])
        self.assertEqual("", result["body"])
        self.assertIn("html_not_rendered", result["partial_reasons"])
        self.assertIn("일반 텍스트를 읽지 못했습니다", result["message"])
        self.assertNotIn("https", str(result))

    def test_non_txt_attachments_are_metadata_only_not_drm_claims(self):
        message = self.sample()
        message.add_attachment(b"SECRET-XLSX", maintype="application", subtype="octet-stream", filename="table.xlsx")
        result = eml.read_eml(self.mail(message))
        self.assertEqual("unsupported_attachment", result["attachments"][0]["code"])
        self.assertIn("TXT 첨부가 아니어서", result["attachments"][0]["message"])
        self.assertEqual([], result["warnings"])
        self.assertNotIn("SECRET-XLSX", str(result))

    def test_protected_attachment_skipped_independently(self):
        message = self.sample()
        message.add_attachment(b"PROTECTED-SECRET", maintype="application", subtype="octet-stream", filename="message.rpmsg")
        result = eml.read_eml(self.mail(message))
        self.assertTrue(result["body_read"])
        self.assertEqual("partial", result["status"])
        self.assertEqual("protection_blocked", result["attachments"][0]["code"])
        self.assertIn("보호된 유형", result["attachments"][0]["message"])
        self.assertNotIn("PROTECTED-SECRET", str(result))

    def test_top_level_protection_does_not_return_subject_or_body(self):
        message = EmailMessage()
        message["Subject"] = "SECRET-SUBJECT"
        message.set_content(b"SECRET-PAYLOAD", maintype="application", subtype="pkcs7-mime")
        result = eml.read_eml(self.mail(message))
        self.assertEqual("blocked", result["status"])
        self.assertFalse(result["ok"])
        self.assertNotIn("SECRET", str(result))

    def test_embedded_eml_not_recursively_read(self):
        message = self.sample()
        nested = EmailMessage()
        nested.set_content("NESTED-SECRET")
        message.add_attachment(nested)
        result = eml.read_eml(self.mail(message))
        self.assertIn("embedded_mail_not_read", result["partial_reasons"])
        self.assertIn("첨부된 메일", result["attachments"][0]["message"])
        self.assertNotIn("NESTED-SECRET", str(result))

    def test_body_and_attachment_output_are_bounded(self):
        message = EmailMessage()
        message.set_content("x" * 30_000)
        for number in range(10):
            message.add_attachment("y" * 10_000, subtype="plain", filename=f"item-{number}.txt")
        result = eml.read_eml(self.mail(message))
        self.assertLessEqual(len(result["body"]), eml.MAX_BODY)
        total = len(result["body"]) + sum(len(a.get("content", "")) for a in result["attachments"])
        self.assertLessEqual(total, eml.MAX_TEXT)
        self.assertIn("text_limit", result["partial_reasons"])

    def test_path_size_and_network_limits_fail_closed(self):
        self.assertEqual("invalid_local_eml_path", eml.read_eml(Path("relative.eml"))["code"])
        self.assertEqual("invalid_local_eml_path", eml.read_eml(self.root / "sample.txt")["code"])
        path = self.root / "oversize.eml"
        path.write_bytes(b"a" * (eml.MAX_BYTES + 1))
        self.assertEqual("eml_size_limit", eml.read_eml(path)["code"])
        with patch.object(eml, "safe_path", side_effect=ValueError("PRIVATE-NETWORK")):
            result = eml.read_eml(path)
            self.assertFalse(result["ok"])
            self.assertNotIn("PRIVATE", str(result))

    def test_unknown_charset_is_not_silently_decoded(self):
        path = self.root / "unknown.eml"
        path.write_bytes(b'Content-Type: text/plain; charset="x-unknown-charset"\r\n\r\nSECRET-BODY')
        result = eml.read_eml(path)
        self.assertFalse(result["body_read"])
        self.assertIn("part_decode_failed", result["partial_reasons"])
        self.assertIn("일반 텍스트를 읽지 못했습니다", result["message"])
        self.assertNotIn("일부만 읽었습니다", result["message"])
        self.assertNotIn("SECRET", str(result))

    def test_many_parts_return_explicit_limit(self):
        message = self.sample()
        for number in range(110):
            message.add_attachment("ok", subtype="plain", filename=f"a-{number}.txt")
        result = eml.read_eml(self.mail(message))
        self.assertIn("mime_part_limit", result["partial_reasons"])
        self.assertLessEqual(len(result["attachments"]), eml.MAX_PARTS)


if __name__ == "__main__":
    unittest.main()
