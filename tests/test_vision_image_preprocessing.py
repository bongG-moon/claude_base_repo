"""Offline checks for bounded, post-permission vision image preprocessing.

No production model, real document, network request or source-file read is used.
"""
import base64
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent import vision_image
from company_agent import vision_routing

try:
    from PIL import Image
except ImportError:
    Image = None


def native_image(data=b"native image bytes", media_type="image/png", *, width=4000, height=2000):
    return {
        "type": "image",
        "file": {
            "base64": base64.b64encode(data).decode("ascii"),
            "type": media_type,
            "originalSize": len(data),
            "dimensions": {
                "originalWidth": width,
                "originalHeight": height,
                "displayWidth": width,
                "displayHeight": height,
            },
            "futureFileField": "preserve me",
        },
        "futureEnvelopeField": {"keep": True},
    }


def raster(width, height, *, kind="PNG", alpha=False, orientation=None):
    mode = "RGBA" if alpha else "RGB"
    color = (30, 120, 220, 96) if alpha else (30, 120, 220)
    with Image.new(mode, (width, height), color) as image:
        output = io.BytesIO()
        kwargs = {}
        if orientation is not None:
            exif = Image.Exif()
            exif[274] = orientation
            kwargs["exif"] = exif
        image.save(output, format=kind, **kwargs)
        return output.getvalue()


def changed_output(result):
    hook = result["hookSpecificOutput"]
    if hook["hookEventName"] != "PostToolUse":
        raise AssertionError("Image replacement must only occur after the Read tool")
    return hook["updatedToolOutput"]


class NativeImageEnvelopeTests(unittest.TestCase):
    def test_small_native_image_is_byte_identical_and_skips_transform(self):
        payload = native_image(width=640, height=360)
        before = copy.deepcopy(payload)
        with patch.object(vision_image, "_transform_image", side_effect=AssertionError("unneeded decode")):
            self.assertEqual({}, vision_image.preprocess_read_result(payload))
        self.assertEqual(before, payload)

    def test_small_image_fast_path_does_not_import_pillow(self):
        import builtins
        original_import = builtins.__import__

        def checked_import(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise AssertionError("ordinary small images must not load the codec")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=checked_import):
            self.assertEqual({}, vision_image.preprocess_read_result(native_image(width=640, height=360)))

    def test_unknown_outputs_are_not_guessed_or_reinterpreted(self):
        cases = [None, "base64 image text", [], {}, {"type": "text", "text": "iVBORw0KGgo="},
                 {"type": "image", "data": "iVBORw0KGgo="},
                 {"content": [{"type": "image", "source": {"type": "base64", "data": "AAAA"}}]},
                 {"type": "image", "file": None}, {"type": "image", "file": {"type": "image/png"}}]
        with patch.object(vision_image, "_transform_image", side_effect=AssertionError("not a native envelope")):
            for payload in cases:
                with self.subTest(payload=payload):
                    self.assertEqual({}, vision_image.preprocess_read_result(payload))

    def test_unsupported_formats_are_unchanged(self):
        with patch.object(vision_image, "_transform_image", side_effect=AssertionError("unsupported codec")):
            for media_type in ("image/gif", "image/webp", "application/pdf", "image/svg+xml", "text/plain", [], {}, None):
                with self.subTest(media_type=media_type):
                    self.assertEqual({}, vision_image.preprocess_read_result(native_image(media_type=media_type)))

    def test_malformed_base64_is_not_repaired(self):
        for encoded in ("not base64!", "AAAA\nAAAA", "AAAA_", "A", 23, None):
            payload = native_image()
            payload["file"]["base64"] = encoded
            with self.subTest(encoded=encoded):
                self.assertEqual({}, vision_image.preprocess_read_result(payload))

    def test_encoded_input_limit_precedes_codec(self):
        payload = native_image(b"x" * 256)
        with patch.object(vision_image, "MAX_INPUT_BYTES", 64), \
                patch.object(vision_image, "_transform_image", side_effect=AssertionError("input too large")):
            self.assertEqual({}, vision_image.preprocess_read_result(payload))

    def test_transform_failure_leaves_original_output_alone(self):
        payload = native_image()
        before = copy.deepcopy(payload)
        with patch.object(vision_image, "_transform_image", return_value=None):
            self.assertEqual({}, vision_image.preprocess_read_result(payload))
        self.assertEqual(before, payload)

    def test_invalid_transform_output_cannot_replace_native_image(self):
        valid = {"data": b"smaller bytes", "mediaType": "image/jpeg", "width": 1000, "height": 500}
        cases = [{**valid, "width": True}, {**valid, "height": -2},
                 {**valid, "width": vision_image.MAX_EDGE + 1},
                 {**valid, "width": 1500, "height": 1500},
                 {**valid, "data": "not bytes"}, {**valid, "data": b""},
                 {**valid, "mediaType": "text/plain"}]
        for transformed in cases:
            with self.subTest(transformed=transformed), \
                    patch.object(vision_image, "_transform_image", return_value=transformed):
                self.assertEqual({}, vision_image.preprocess_read_result(native_image()))

    def test_optional_codec_exception_never_becomes_a_tool_failure(self):
        with patch.object(vision_image, "_transform_image", side_effect=RuntimeError("codec failure")):
            self.assertEqual({}, vision_image.preprocess_read_result(native_image()))

    def test_absent_pillow_keeps_native_result_without_process_or_install(self):
        import builtins
        original_import = builtins.__import__

        def checked_import(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("optional codec not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=checked_import), \
                patch("subprocess.run", side_effect=AssertionError("no fallback process")), \
                patch("subprocess.Popen", side_effect=AssertionError("no installer")), \
                patch("socket.socket", side_effect=AssertionError("no network")):
            self.assertEqual({}, vision_image.preprocess_read_result(native_image()))

    def test_replacement_preserves_native_envelope_and_original_measurements(self):
        payload = native_image()
        payload["file"]["dimensions"]["futureDimension"] = "kept"
        before = copy.deepcopy(payload)
        transformed = {"data": b"smaller bytes", "mediaType": "image/jpeg", "width": 1400, "height": 700}
        with patch.object(vision_image, "_transform_image", return_value=transformed):
            result = vision_image.preprocess_read_result(payload)
        output = changed_output(result)
        self.assertEqual(before, payload, "the tool payload is never mutated in place")
        self.assertEqual(before["futureEnvelopeField"], output["futureEnvelopeField"])
        self.assertEqual("preserve me", output["file"]["futureFileField"])
        self.assertEqual(before["file"]["originalSize"], output["file"]["originalSize"])
        dims = output["file"]["dimensions"]
        self.assertEqual(4000, dims["originalWidth"])
        self.assertEqual(2000, dims["originalHeight"])
        self.assertEqual("kept", dims["futureDimension"])
        self.assertEqual((1400, 700), (dims["displayWidth"], dims["displayHeight"]))
        self.assertEqual("image/jpeg", output["file"]["type"])
        self.assertEqual(b"smaller bytes", base64.b64decode(output["file"]["base64"]))
        self.assertNotIn("additionalContext", result["hookSpecificOutput"], "no repeated model instructions")
        self.assertNotIn("permissionDecision", result["hookSpecificOutput"])

    def test_missing_original_dimensions_are_not_invented(self):
        payload = native_image()
        payload["file"].pop("dimensions")
        transformed = {"data": b"smaller bytes", "mediaType": "image/png", "width": 800, "height": 400}
        with patch.object(vision_image, "_transform_image", return_value=transformed):
            output = changed_output(vision_image.preprocess_read_result(payload))
        self.assertNotIn("originalWidth", output["file"]["dimensions"])
        self.assertNotIn("originalHeight", output["file"]["dimensions"])
        self.assertEqual((800, 400), (output["file"]["dimensions"]["displayWidth"],
                                     output["file"]["dimensions"]["displayHeight"]))


@unittest.skipUnless(Image is not None, "Pillow is optional; raster codec checks need the test dependency")
class RasterPreprocessingTests(unittest.TestCase):
    def assert_bounded_image(self, result, aspect):
        output = changed_output(result)
        data = base64.b64decode(output["file"]["base64"], validate=True)
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            self.assertLessEqual(max(width, height), vision_image.MAX_EDGE)
            self.assertLessEqual(width * height, vision_image.MAX_PIXELS)
            self.assertLessEqual(len(data), vision_image.MAX_BYTES)
            self.assertAlmostEqual(width / height, aspect, delta=0.01)
            self.assertEqual((width, height), (output["file"]["dimensions"]["displayWidth"],
                                             output["file"]["dimensions"]["displayHeight"]))
        return output

    def test_large_png_is_downscaled_in_memory(self):
        data = raster(3600, 1800)
        result = vision_image.preprocess_read_result(native_image(data, width=3600, height=1800))
        self.assert_bounded_image(result, 2)

    def test_large_jpeg_preserves_aspect_ratio_and_media_type(self):
        data = raster(2560, 1440, kind="JPEG")
        result = vision_image.preprocess_read_result(native_image(data, "image/jpeg", width=2560, height=1440))
        output = self.assert_bounded_image(result, 2560 / 1440)
        self.assertEqual("image/jpeg", output["file"]["type"])

    def test_pixel_area_limit_also_applies_to_square_images(self):
        data = raster(1500, 1500)
        result = vision_image.preprocess_read_result(native_image(data, width=1500, height=1500))
        self.assert_bounded_image(result, 1)

    def test_oversized_encoded_png_checks_bytes_even_with_small_dimensions(self):
        width, height = 700, 450
        with Image.frombytes("RGB", (width, height), random.Random(7).randbytes(width * height * 3)) as image:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            data = buffer.getvalue()
        self.assertGreater(len(data), vision_image.MAX_BYTES)
        result = vision_image.preprocess_read_result(native_image(data, width=width, height=height))
        output = self.assert_bounded_image(result, width / height)
        self.assertEqual("image/jpeg", output["file"]["type"])
        self.assertEqual((width, height), (output["file"]["dimensions"]["displayWidth"],
                                         output["file"]["dimensions"]["displayHeight"]))

    def test_transparency_is_preserved_as_png(self):
        data = raster(2400, 1600, alpha=True)
        result = vision_image.preprocess_read_result(native_image(data, width=2400, height=1600))
        output = self.assert_bounded_image(result, 1.5)
        self.assertEqual("image/png", output["file"]["type"])
        with Image.open(io.BytesIO(base64.b64decode(output["file"]["base64"]))) as image:
            self.assertIn("A", image.getbands())
            self.assertEqual((96, 96), image.getchannel("A").getextrema())

    def test_actual_small_image_is_not_upscaled_even_if_metadata_is_large(self):
        data = raster(320, 180)
        payload = native_image(data, width=4000, height=2000)
        self.assertEqual({}, vision_image.preprocess_read_result(payload))

    def test_incorrect_declared_mime_is_not_silently_changed(self):
        data = raster(2000, 1200)
        self.assertEqual({}, vision_image.preprocess_read_result(native_image(data, "image/jpeg")))

    def test_corrupted_image_is_passed_through_without_error_loop(self):
        self.assertEqual({}, vision_image.preprocess_read_result(native_image(b"invalid image data" * 200)))

    def test_decoded_pixel_safety_limit_is_enforced(self):
        data = raster(100, 100)
        with patch.object(vision_image, "MAX_INPUT_PIXELS", 1000):
            self.assertEqual({}, vision_image.preprocess_read_result(native_image(data)))

    def test_exif_rotation_is_not_reinterpreted(self):
        data = raster(2000, 1200, kind="JPEG", orientation=6)
        self.assertEqual({}, vision_image.preprocess_read_result(native_image(data, "image/jpeg")))

    def test_animated_png_is_not_flattened(self):
        with Image.new("RGB", (2000, 1000), "red") as first, Image.new("RGB", (2000, 1000), "blue") as second:
            buffer = io.BytesIO()
            first.save(buffer, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
        self.assertEqual({}, vision_image.preprocess_read_result(native_image(buffer.getvalue())))

    def test_unachievable_transparent_byte_budget_keeps_original(self):
        data = raster(2000, 1200, alpha=True)
        with patch.object(vision_image, "MAX_BYTES", 10):
            self.assertEqual({}, vision_image.preprocess_read_result(native_image(data)))

    def test_missing_original_dimensions_are_not_invented(self):
        payload = native_image(raster(2000, 1200))
        payload["file"].pop("dimensions")
        output = changed_output(vision_image.preprocess_read_result(payload))
        self.assertEqual({"displayWidth", "displayHeight"}, set(output["file"]["dimensions"]))

    def test_processing_does_not_read_source_files_or_use_network(self):
        data = raster(2200, 1200)
        Image.init()  # Codec imports may legitimately read their own package once.
        with patch("builtins.open", side_effect=AssertionError("source file read")), \
                patch.object(Path, "open", side_effect=AssertionError("source file read")), \
                patch("socket.socket", side_effect=AssertionError("network")), \
                patch("subprocess.run", side_effect=AssertionError("not needed with Pillow")):
            result = vision_image.preprocess_read_result(native_image(data, width=2200, height=1200))
        self.assert_bounded_image(result, 2200 / 1200)


class VisionResultActivationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"ANTHROPIC_CUSTOM_MODEL_OPTION": vision_routing.VISION_MODEL})
        env.start()
        self.addCleanup(env.stop)

    def payload(self, **extra):
        return {"tool_name": "Read", "tool_input": {"file_path": r"C:\approved\image.png"},
                "agent_type": vision_routing.VISION_AGENT, "agent_id": "vision-child",
                "tool_response": native_image(), **extra}

    def test_only_post_permission_vision_child_read_is_processed(self):
        sentinel = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "sentinel"}}
        with patch.object(vision_image, "preprocess_read_result", return_value=sentinel) as process:
            self.assertEqual(sentinel, vision_routing.result_context("PostToolUse", self.payload()))
            process.assert_called_once_with(self.payload()["tool_response"])

    def test_unrelated_results_and_failures_never_load_images(self):
        cases = [
            ("PostToolUseFailure", self.payload()),
            ("PreToolUse", self.payload()),
            ("PostToolUse", self.payload(agent_id="")),
            ("PostToolUse", self.payload(agent_type="general-purpose")),
            ("PostToolUse", self.payload(tool_name="mcp__playwright__browser_take_screenshot")),
            ("PostToolUse", self.payload(tool_name="mcp__local-computer-use__zoom")),
            ("PostToolUse", self.payload(tool_name="Bash")),
            ("PostToolUse", self.payload(tool_input={"file_path": "document.pdf"})),
            ("PostToolUse", self.payload(tool_input={"file_path": "notes.md"})),
        ]
        with patch.object(vision_image, "preprocess_read_result", side_effect=AssertionError("unrelated image work")):
            for event, payload in cases:
                with self.subTest(event=event, tool=payload["tool_name"], identity=payload.get("agent_type")):
                    vision_routing.result_context(event, payload)

    def test_unconfigured_environment_keeps_existing_behavior(self):
        with patch.dict(os.environ, {"ANTHROPIC_CUSTOM_MODEL_OPTION": ""}), \
                patch.object(vision_image, "preprocess_read_result", side_effect=AssertionError("no opt-in")):
            self.assertEqual({}, vision_routing.result_context("PostToolUse", self.payload()))

    @unittest.skipIf(Image is None, "optional Pillow codec")
    def test_native_entry_returns_scoped_image_without_learning_or_extra_tools(self):
        import native_entry
        payload = self.payload(tool_response=native_image(raster(2000, 1200)))
        for active in (True, False):
            output = io.StringIO()
            with patch.object(sys, "argv", ["native_entry.py", "--event", "PostToolUse"]), \
                    patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                    patch.object(native_entry, "configure_runtime", return_value=active), \
                    patch("company_agent.hook_diagnostics.record_hook", side_effect=AssertionError("no new workflow")), \
                    patch("subprocess.Popen", side_effect=AssertionError("no extra tools")), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(0, native_entry.main())
            result = json.loads(output.getvalue())
            if active:
                self.assertEqual("image", changed_output(result)["type"])
                self.assertNotIn("permissionDecision", result["hookSpecificOutput"])
            else:
                self.assertEqual({}, result)


if __name__ == "__main__":
    unittest.main()
