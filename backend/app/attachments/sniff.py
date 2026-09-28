"""Identify an upload by its bytes, never by the client's Content-Type or extension.

Only containers are recognised here; whether an image or document actually decodes
is checked later (Pillow re-encode, text extraction).
"""

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal

type AttachmentKind = Literal["image", "audio", "document"]


@dataclass(frozen=True)
class Detected:
    kind: AttachmentKind
    mime_type: str


class UnsupportedFileType(Exception):
    pass


# mp4 "brands" (bytes 8-12 of the ftyp box) used by audio-only files: iTunes m4a,
# plus the generic ones Safari's MediaRecorder writes for audio/mp4.
_MP4_BRANDS = (b"M4A ", b"M4B ", b"mp42", b"mp41", b"isom", b"iso5", b"iso6", b"dash")

_TEXT_SUFFIXES = {".txt": "text/plain", ".md": "text/markdown", ".markdown": "text/markdown"}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def detect(data: bytes, filename: str) -> Detected:
    head = data[:16]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Detected("image", "image/png")
    if head.startswith(b"\xff\xd8\xff"):
        return Detected("image", "image/jpeg")
    if head.startswith((b"GIF87a", b"GIF89a")):
        return Detected("image", "image/gif")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return Detected("image", "image/webp")
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return Detected("audio", "audio/wav")
    if head.startswith(b"\x1a\x45\xdf\xa3"):  # EBML: Matroska / WebM (Chrome's recorder)
        return Detected("audio", "audio/webm")
    if head.startswith(b"OggS"):
        return Detected("audio", "audio/ogg")
    if head[4:8] == b"ftyp" and head[8:12] in _MP4_BRANDS:
        return Detected("audio", "audio/mp4")
    if head.startswith(b"ID3") or _is_mp3_frame(head):
        return Detected("audio", "audio/mpeg")
    if head.startswith(b"%PDF-"):
        return Detected("document", "application/pdf")
    if head.startswith(b"PK\x03\x04") and _is_docx(data):
        return Detected("document", DOCX_MIME)
    suffix = PurePath(filename).suffix.lower()
    if suffix in _TEXT_SUFFIXES and _is_text(data):
        return Detected("document", _TEXT_SUFFIXES[suffix])
    raise UnsupportedFileType


def _is_mp3_frame(head: bytes) -> bool:
    # 11-bit frame sync plus layer bits == 01 (Layer III). Checking the layer keeps
    # e.g. a UTF-16 BOM (FF FE) from passing as audio.
    return len(head) > 1 and head[0] == 0xFF and head[1] & 0xE6 == 0xE2


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
