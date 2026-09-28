"""Re-encode uploaded images (ADR 0008 §3).

Decoding and re-encoding proves the file really is an image, drops EXIF (phone photos
carry GPS coordinates), applies the EXIF orientation first so the picture isn't turned
sideways, and caps the size models are sent. Output is JPEG: every vision API accepts
it, which is not true of WebP on every OpenAI-compatible relay.
"""

import io
import math
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_EDGE = 1600
# Decompression-bomb guard: a small file can declare a huge canvas. 50 MP covers any
# phone camera; beyond it Pillow refuses before allocating.
MAX_PIXELS = 50_000_000
JPEG_QUALITY = 90
_ALLOWED_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}


class InvalidImage(Exception):
    pass


@dataclass(frozen=True)
class NormalizedImage:
    data: bytes
    mime_type: str
    width: int
    height: int


def normalize_image(data: bytes) -> NormalizedImage:
    """CPU-bound: call it from a worker thread."""
    try:
        with warnings.catch_warnings():
            # Between MAX_PIXELS and 2x Pillow only warns; make that an error too.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in _ALLOWED_FORMATS:
                    raise InvalidImage(f"unsupported image format {image.format}")
                if image.width * image.height > MAX_PIXELS:
                    raise InvalidImage("image dimensions too large")
                image.seek(0)  # animated GIF/WebP: first frame only
                # JPEG only: decode at a reduced DCT scale (still >= MAX_EDGE), so a
                # 50 MP phone photo doesn't need ~150 MB of RAM on a small server.
                scale = MAX_EDGE / max(image.width, image.height)
                if scale < 1:
                    image.draft(
                        "RGB", (math.ceil(image.width * scale), math.ceil(image.height * scale))
                    )
                frame = ImageOps.exif_transpose(image)
                frame.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
                frame = _flatten(frame)
                out = io.BytesIO()
                # No exif= argument: the new file carries no metadata at all.
                frame.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidImage("not a readable image") from None
    except OSError as exc:  # truncated or corrupt data
        raise InvalidImage("not a readable image") from exc
    return NormalizedImage(out.getvalue(), "image/jpeg", frame.width, frame.height)


def _flatten(image: Image.Image) -> Image.Image:
    """JPEG has no alpha: composite transparent images onto white (screenshots, PNGs)."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")
