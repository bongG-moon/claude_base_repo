"""Bounded, post-permission adaptation of native Read image results for HCP.

Only bytes already returned by Read are used. No source-file access, cache,
model calls, settings discovery, or package installation. Native Read already
preprocesses images; small results must stay untouched. These conservative
transport limits are NOT a claim about the HCP model's context window.
"""
from __future__ import annotations

import base64
import io
import math
from typing import Any
import warnings

MAX_EDGE = 1568
MAX_PIXELS = 1_150_000
MAX_BYTES = 512_000
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_INPUT_PIXELS = 20_000_000
_MIME_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG"}


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _fits(width: int, height: int) -> bool:
    return max(width, height) <= MAX_EDGE and width * height <= MAX_PIXELS


def _pillow_transform(data: bytes, media_type: str, Image: Any) -> dict[str, Any] | None:
    # Never disable Pillow's own decompression protections or accept truncated
    # image data. Metadata from the hook is not trusted for decoder allocation.
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            width, height = source.size
            if (source.format != _MIME_FORMATS[media_type]
                    or width * height > MAX_INPUT_PIXELS
                    or getattr(source, "n_frames", 1) != 1
                    or source.getexif().get(274, 1) != 1):
                return None
            if _fits(width, height) and len(data) <= MAX_BYTES:
                return None
            factor = min(1.0, MAX_EDGE / max(width, height),
                         math.sqrt(MAX_PIXELS / (width * height)))
            target = (max(1, int(width * factor)), max(1, int(height * factor)))
            alpha = "A" in source.getbands() or "transparency" in source.info
            converted = source.convert("RGBA" if alpha else "RGB")
            try:
                resized = converted.resize(target, Image.Resampling.LANCZOS) if target != source.size else converted.copy()
                try:
                    # Copy only pixels: do not forward EXIF, comments, or other
                    # metadata. Alpha must never become a black JPEG background.
                    resized.info.clear()
                    output = io.BytesIO()
                    output_type = media_type
                    if media_type == "image/png" or alpha:
                        resized.save(output, format="PNG", compress_level=6)
                        output_type = "image/png"
                    if (media_type == "image/jpeg" or len(output.getvalue()) > MAX_BYTES) and not alpha:
                        output_type = "image/jpeg"
                        for quality in (90, 80):
                            output = io.BytesIO()
                            resized.save(output, format="JPEG", quality=quality, subsampling=0)
                            if output.tell() <= MAX_BYTES:
                                break
                    result = output.getvalue()
                    if not result or len(result) > MAX_BYTES or result == data:
                        return None
                    return {"data": result, "mediaType": output_type, "width": target[0], "height": target[1]}
                finally:
                    resized.close()
            finally:
                converted.close()


def _transform_image(data: bytes, media_type: str) -> dict[str, Any] | None:
    try:
        from PIL import Image
    except ImportError:
        # Native Read already preprocesses images. Starting another Windows
        # codec process measured slower than the hook budget; never add it,
        # package installation, or a model-side recovery loop to this path.
        return None
    return _pillow_transform(data, media_type, Image)


def preprocess_read_result(response: Any) -> dict[str, Any]:
    """Return an overwrite ONLY after a successful, useful transformation.

    Native Read's exact image envelope is required. Text/base64 dumps, MCP
    captures, PDF pages and unknown shapes are never guessed or rewritten.
    Optional adaptation errors must not introduce another tool failure loop.
    """
    if not isinstance(response, dict) or response.get("type") != "image":
        return {}
    file = response.get("file")
    if not isinstance(file, dict):
        return {}
    media_type = file.get("type")
    if not isinstance(media_type, str) or media_type not in _MIME_FORMATS:
        return {}
    encoded = file.get("base64")
    if (not isinstance(encoded, str) or not encoded
            or len(encoded) > ((MAX_INPUT_BYTES + 2) // 3) * 4
            or not _positive_int(file.get("originalSize"))):
        return {}
    dimensions = file.get("dimensions", {})
    if not isinstance(dimensions, dict):
        return {}
    width, height = dimensions.get("displayWidth"), dimensions.get("displayHeight")
    # The current CLI normally already supplies bounded display dimensions.
    # Do not even decode/import a codec on that common path.
    if (_positive_int(width) and _positive_int(height) and _fits(width, height)
            and len(encoded) <= (MAX_BYTES // 3) * 4):
        return {}
    try:
        data = base64.b64decode(encoded, validate=True)
        if not data or len(data) > MAX_INPUT_BYTES:
            return {}
        updated = _transform_image(data, media_type)
        if not isinstance(updated, dict):
            return {}
        width, height = updated.get("width"), updated.get("height")
        result, media_type = updated.get("data"), updated.get("mediaType")
        if (not _positive_int(width) or not _positive_int(height) or not _fits(width, height)
                or not isinstance(result, bytes) or not result or len(result) > MAX_BYTES
                or media_type not in _MIME_FORMATS or result == data):
            return {}
        output = {**response, "file": {**file, "base64": base64.b64encode(result).decode("ascii"),
                   "type": media_type, "dimensions": {**dimensions, "displayWidth": width, "displayHeight": height}}}
        # Do not repeat instructions/tokens or announce success separately:
        # older clients may ignore replacement fields. The worker already has
        # the unreadable-text rule, and display dimensions live in the envelope.
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": output}}
    except Exception:
        # No raw image, path, credential, or exception details are logged. Keep
        # native output, not a broken replacement, on unsupported environments.
        return {}
