"""
Shared square image upload pipeline (player avatars, alliance logos).

Owner for processing only — persistence stays in playercard / alliance modules.
"""

from __future__ import annotations

import io
from typing import Any, Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

UPLOAD_MAX_BYTES = 2 * 1024 * 1024
OUTPUT_SIZE = 256
WEBP_QUALITY = 80
MIN_FILE_BYTES = 64
BLOB_MIME = "image/webp"

_ALLOWED_MIME = frozenset({"image/png", "image/jpeg", "image/webp"})


def read_upload_bytes(file_storage: Any) -> Tuple[Optional[bytes], str]:
    if file_storage is None:
        return None, "image_upload_missing"
    raw = file_storage.read()
    if not raw:
        return None, "image_upload_missing"
    if len(raw) > UPLOAD_MAX_BYTES:
        return None, "image_upload_too_large"
    return raw, ""


def validate_upload_image(file_storage: Any, raw: bytes) -> Tuple[bool, str]:
    mime = str(getattr(file_storage, "mimetype", "") or "").split(";")[0].strip().lower()
    if mime in _ALLOWED_MIME:
        return True, mime
    try:
        with Image.open(io.BytesIO(raw)) as src:
            fmt = str(src.format or "").upper()
    except Exception:
        return False, "image_upload_invalid_type"
    sniffed = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "WEBP": "image/webp",
    }.get(fmt)
    if sniffed:
        return True, sniffed
    return False, "image_upload_invalid_type"


def process_square_image(src: Image.Image, *, size: int = OUTPUT_SIZE) -> Image.Image:
    im = ImageOps.exif_transpose(src)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
    else:
        im = im.convert("RGB")
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    im = im.crop((left, top, left + side, top + side))
    return im.resize((int(size), int(size)), Image.Resampling.LANCZOS)


def webp_bytes_from_image(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    has_alpha = im.mode in ("RGBA", "LA") or "A" in im.getbands()
    if has_alpha:
        im.save(buf, "WEBP", quality=WEBP_QUALITY, method=6, lossless=False)
    else:
        im.convert("RGB").save(buf, "WEBP", quality=WEBP_QUALITY, method=6)
    data = buf.getvalue()
    if len(data) < MIN_FILE_BYTES:
        raise ValueError("image_output_too_small")
    return data


def blob_from_raw(raw: bytes, *, size: int = OUTPUT_SIZE) -> Tuple[Optional[bytes], str]:
    try:
        with Image.open(io.BytesIO(raw)) as src:
            fmt = str(src.format or "").upper()
            if fmt in ("GIF", "SVG", "MPO"):
                return None, "image_upload_invalid_type"
            if src.size[0] < 32 or src.size[1] < 32:
                return None, "image_upload_invalid_type"
            im = process_square_image(src, size=size)
        return webp_bytes_from_image(im), ""
    except UnidentifiedImageError:
        return None, "image_upload_invalid_type"
    except ValueError:
        return None, "image_upload_invalid_type"
    except Exception:
        return None, "image_upload_invalid_type"


def blob_from_upload(file_storage: Any, *, size: int = OUTPUT_SIZE) -> Tuple[Optional[bytes], str]:
    raw, err = read_upload_bytes(file_storage)
    if raw is None:
        return None, err

    ok_mime, _mime_err = validate_upload_image(file_storage, raw)
    if not ok_mime:
        return None, "image_upload_invalid_type"
    return blob_from_raw(raw, size=size)
