"""Opt-in diagnostic kit contracts. No external services or credentials required."""
import base64
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
import zlib


KIT = Path(__file__).resolve().parents[1] / "standalone-guides" / "vision-input-check"
SPEC = importlib.util.spec_from_file_location("vision_input_check", KIT / "compare_inputs.py")
kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kit)


class VisionInputCheckTests(unittest.TestCase):
    def test_fixtures_are_valid_small_deterministic_pngs(self):
        for number in (1, 2):
            data = kit.fixture_png(number)
            self.assertEqual(data, kit.fixture_png(number))
            self.assertEqual(data, (KIT / f"sample-{number:02}.png").read_bytes())
            self.assertLess(len(data), 10_000)
            self.assertEqual(struct.unpack(">II", data[16:24]), (640, 360))
            offset, packed = 8, b""
            while offset < len(data):
                length = struct.unpack(">I", data[offset:offset + 4])[0]
                kind = data[offset + 4:offset + 8]
                content = data[offset + 8:offset + 8 + length]
                checksum = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0]
                self.assertEqual(checksum, zlib.crc32(kind + content) & 0xffffffff)
                if kind == b"IDAT":
                    packed += content
                offset += 12 + length
            self.assertEqual(len(zlib.decompress(packed)), (640 * 3 + 1) * 360)

    def test_request_images_are_byte_identical_and_base64_not_text(self):
        data = kit.fixture_png(1)
        rows = kit.build_requests(data, "HCP-Vision-Latest")
        a, b = rows.values()
        ai = a["messages"][0]["content"][0]
        bi = b["messages"][2]["content"][0]["content"][0]
        self.assertEqual(ai, bi)
        self.assertEqual(ai["type"], "image")
        self.assertEqual(base64.b64decode(ai["source"]["data"]), data)

    def test_valid_tool_use_pair_and_comparison_constants(self):
        a, b = kit.build_requests(kit.fixture_png(1), "HCP-Vision-Latest").values()
        for key in ("model", "system", "max_tokens", "tools", "tool_choice"):
            self.assertEqual(a[key], b[key])
        self.assertEqual(a["messages"][0]["content"][1]["text"], b["messages"][0]["content"][0]["text"])
        use = b["messages"][1]["content"][0]
        result = b["messages"][2]["content"][0]
        self.assertEqual(use["id"], result["tool_use_id"])
        self.assertEqual(use["name"], "Read")
        self.assertEqual(b["messages"][1]["role"], "assistant")
        self.assertEqual(b["messages"][2]["role"], "user")
        self.assertEqual(result["type"], "tool_result")

    def test_no_answer_key_leaks_into_text_prompt_or_tool_arguments(self):
        requests = kit.build_requests(kit.fixture_png(1), "HCP-Vision-Latest")
        def collect_text(obj):
            if isinstance(obj, dict):
                return " ".join(collect_text(v) for k, v in obj.items() if k != "data")
            if isinstance(obj, list):
                return " ".join(map(collect_text, obj))
            return str(obj)
        text = collect_text(requests)
        for answer in ("M7K2", "A1", "B8", "K2", "R5", "T9"):
            self.assertNotIn(answer, text)
        self.assertNotIn("sample-01", text)

    def test_default_run_never_reads_credentials_or_network(self):
        out = io.StringIO()
        with mock.patch.object(kit, "os") as fake_os, mock.patch.object(kit.getpass, "getpass", side_effect=AssertionError("credential input")), mock.patch.object(kit.request, "build_opener", side_effect=AssertionError("network")), redirect_stdout(out):
            self.assertEqual(kit.main([]), 0)
            fake_os.environ.get.assert_not_called()
        report = json.loads(out.getvalue())
        self.assertEqual(report["network_calls"], 0)
        self.assertFalse(report["credentials_read"])
        self.assertNotIn("base64", out.getvalue())

    def test_urls_require_explicit_approved_target_and_secure_default(self):
        self.assertEqual(kit.endpoint("https://approved.example/api"), "https://approved.example/api/v1/messages")
        self.assertEqual(kit.endpoint("https://approved.example/v1/"), "https://approved.example/v1/messages")
        self.assertEqual(kit.endpoint("https://approved.example/v1/messages"), "https://approved.example/v1/messages")
        for url in ("", "http://approved.example", "https://user:secret@example.test", "https://example.test?key=secret", "https://example.test#key", "file:///tmp", "https://example.test\n", "https://example.test\\@evil.test", "https://example.test:invalid"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                kit.endpoint(url)
        self.assertEqual(kit.endpoint("http://approved.example", True), "http://approved.example/v1/messages")

    def test_every_redirect_is_denied(self):
        req = kit.request.Request("https://approved.example/v1/messages", headers={"Authorization": "Bearer secret"})
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code), self.assertRaises(HTTPError):
                kit.NoRedirect().redirect_request(req, None, code, "moved", {}, "https://other.example")

    def test_redirect_error_saves_neither_body_nor_location_or_key(self):
        body = mock.Mock()
        exception = HTTPError("https://approved.example", 302, "secret", {"Location": "https://secret.example"}, body)
        opener = mock.Mock()
        opener.open.side_effect = exception
        with mock.patch.object(kit.request, "build_opener", return_value=opener):
            result = kit.send_once("https://approved.example", {}, "secret", "bearer", 1)
        self.assertEqual(result["outcome"], "redirect_blocked")
        body.read.assert_not_called()
        body.close.assert_called_once()
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(opener.open.call_count, 1)

    def test_response_is_sanitized_bounded_and_not_automatically_passed(self):
        response = {"model": "reported-model", "stop_reason": "end_turn", "usage": {"input_tokens": 80, "output_tokens": 30, "other": "secret", "cache_read_input_tokens": -1}, "content": [{"type": "text", "text": "secret Bearer abcdef data:image/png;base64,ABCDEF== " + "A" * 150 + " 판독 성공 " + "한" * 5000}]}
        result = kit.summarize_response(json.dumps(response).encode(), "secret")
        self.assertEqual(result["vision_judgment"], "human_review_required")
        self.assertEqual(result["outcome"], "response_received")
        self.assertLessEqual(len(result["text"]), 4000)
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("ABCDEF", result["text"])
        self.assertEqual(result["usage"], {"input_tokens": 80, "output_tokens": 30})

    def test_no_text_or_invalid_response_is_not_visual_success(self):
        result = kit.summarize_response(b'{"content":[]}', "")
        self.assertEqual(result["outcome"], "no_text_response")
        with self.assertRaises(ValueError):
            kit.summarize_response(b'{"error":{"text":"secret"}}', "secret")

    def test_response_read_is_bounded(self):
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = b"x" * (kit.MAX_RESPONSE_BYTES + 1)
        opener = mock.Mock()
        opener.open.return_value.__enter__ = mock.Mock(return_value=response)
        opener.open.return_value.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(kit.request, "build_opener", return_value=opener):
            result = kit.send_once("https://approved.example", {}, "secret", "bearer", 3)
        self.assertEqual(result["outcome"], "response_too_large")
        response.read.assert_called_once_with(kit.MAX_RESPONSE_BYTES + 1)

    def test_existing_output_is_never_overwritten_or_sent(self):
        with tempfile.TemporaryDirectory(dir=KIT) as temp:
            sentinel = Path(temp) / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with mock.patch.object(kit, "send_once", side_effect=AssertionError("must not send")), mock.patch.object(kit, "os") as fake_os, redirect_stderr(io.StringIO()):
                self.assertEqual(kit.main(["--send", "--base-url", "https://approved.example", "--output", temp]), 2)
                fake_os.environ.get.assert_not_called()
            self.assertEqual(sentinel.read_text(), "keep")

    def test_send_requires_explicit_url_and_does_not_probe_settings(self):
        with mock.patch.object(kit, "send_once", side_effect=AssertionError("must not send")), mock.patch.object(kit, "os") as fake_os, redirect_stderr(io.StringIO()):
            self.assertEqual(kit.main(["--send"]), 2)
            fake_os.environ.get.assert_not_called()

    def test_explicit_send_only_two_calls_and_safe_report(self):
        with tempfile.TemporaryDirectory(dir=KIT) as temp:
            output = Path(temp) / "new"
            with mock.patch.dict(kit.os.environ, {"VISION_TEST_TOKEN": "test-secret"}), mock.patch.object(kit, "send_once", return_value={"outcome": "response_received", "vision_judgment": "human_review_required", "text": "observed"}) as send, redirect_stdout(io.StringIO()):
                self.assertEqual(kit.main(["--send", "--base-url", "https://approved.example", "--output", str(output)]), 0)
            self.assertEqual(send.call_count, 2)
            report = (output / "comparison.json").read_text(encoding="utf-8")
            self.assertNotIn("test-secret", report)
            self.assertNotIn("base64", report)
            self.assertNotIn("approved.example", report)
            self.assertTrue(json.loads(report)["B_is_synthetic_not_real_cli"])

    def test_guide_is_offline_and_distinguishes_synthetic_and_human_review(self):
        html = (KIT / "시작하기.html").read_text(encoding="utf-8")
        self.assertNotRegex(html, r"(?i)<script|<link|@import|url\(")
        self.assertIn("B는 실제 CLI가 아니라", html)
        self.assertIn("정확히 읽었다는 판정은 다릅니다", html)
        self.assertIn("자동 실행 없음", html)
        self.assertIn("sample-01.png", html)


if __name__ == "__main__":
    unittest.main()
