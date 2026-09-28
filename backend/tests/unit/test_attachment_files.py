import io
import zipfile

import pytest
from PIL import Image

from app.attachments.images import MAX_EDGE, InvalidImage, normalize_image
from app.attachments.service import clean_filename
from app.attachments.sniff import DOCX_MIME, UnsupportedFileType, detect


def image_bytes(
    fmt: str, size: tuple[int, int] = (40, 30), mode: str = "RGB", **save: object
) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, "red").save(out, fmt, **save)
    return out.getvalue()


def docx_bytes() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    return out.getvalue()


@pytest.mark.parametrize(
    ("data", "filename", "kind", "mime"),
    [
        (image_bytes("PNG"), "x.bin", "image", "image/png"),
        (image_bytes("JPEG"), "x", "image", "image/jpeg"),
        (image_bytes("GIF"), "x", "image", "image/gif"),
        (image_bytes("WEBP"), "x", "image", "image/webp"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "a", "audio", "audio/wav"),
        (b"\x1a\x45\xdf\xa3\x01\x00\x00\x00", "rec", "audio", "audio/webm"),
        (b"OggS\x00\x02" + b"\x00" * 10, "a", "audio", "audio/ogg"),
        (b"\x00\x00\x00\x20ftypM4A \x00\x00", "a", "audio", "audio/mp4"),
        (b"\x00\x00\x00\x20ftypisom\x00\x00", "a", "audio", "audio/mp4"),
        (b"ID3\x04\x00" + b"\x00" * 11, "a", "audio", "audio/mpeg"),
        (b"\xff\xfb\x90\x00" + b"\x00" * 12, "a", "audio", "audio/mpeg"),
        (b"%PDF-1.7\n", "doc", "document", "application/pdf"),
        (docx_bytes(), "doc", "document", DOCX_MIME),
        ("Hello 世界\n".encode(), "notes.TXT", "document", "text/plain"),
        (b"# Title", "notes.md", "document", "text/markdown"),
    ],
)
def test_detect_by_content(data: bytes, filename: str, kind: str, mime: str) -> None:
    detected = detect(data, filename)
    assert (detected.kind, detected.mime_type) == (kind, mime)


@pytest.mark.parametrize(
    ("data", "filename"),
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "logo.svg"),  # would run script inline
        (b"<html><script>", "page.txt.html"),
        (b"MZ\x90\x00", "setup.exe"),
        (b"PK\x03\x04not really a zip", "x.docx"),  # zip magic but no Word document
        (b"\x00\x01binary", "data.txt"),  # txt must really be text
        (b"\xff\xfe\x00latin", "notes.txt"),
        (b"plain words", "notes.csv"),  # text only for .txt/.md
        (b"", "empty.txt.png"),
    ],
)
def test_detect_rejects_other_files(data: bytes, filename: str) -> None:
    with pytest.raises(UnsupportedFileType):
        detect(data, filename)


def test_client_declared_type_is_irrelevant() -> None:
    # A PNG named .pdf is a PNG; a PDF named .png is a PDF.
    assert detect(image_bytes("PNG"), "doc.pdf").mime_type == "image/png"
    assert detect(b"%PDF-1.4", "photo.png").mime_type == "application/pdf"


def test_normalize_downscales_and_reencodes_as_jpeg() -> None:
    result = normalize_image(image_bytes("PNG", (3200, 800)))

    assert result.mime_type == "image/jpeg"
    assert (result.width, result.height) == (MAX_EDGE, 400)
    with Image.open(io.BytesIO(result.data)) as decoded:
        assert decoded.format == "JPEG"
        assert decoded.size == (MAX_EDGE, 400)


def test_normalize_keeps_small_images_small() -> None:
    result = normalize_image(image_bytes("JPEG", (640, 480)))
    assert (result.width, result.height) == (640, 480)


def test_normalize_strips_exif_but_applies_orientation() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° CW to display
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x8825] = {1: "N", 2: (39.0, 54.0, 0.0)}  # GPS IFD
    source = image_bytes("JPEG", (400, 200), exif=exif)

    result = normalize_image(source)

    with Image.open(io.BytesIO(result.data)) as decoded:
        assert decoded.size == (200, 400)  # turned upright
        assert not decoded.getexif()
        assert "exif" not in decoded.info


def test_normalize_flattens_transparency_onto_white() -> None:
    out = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(out, "PNG")

    result = normalize_image(out.getvalue())

    with Image.open(io.BytesIO(result.data)) as decoded:
        r, g, b = decoded.convert("RGB").getpixel((5, 5))  # type: ignore[misc]
        assert min(r, g, b) > 240


def test_normalize_takes_the_first_gif_frame() -> None:
    out = io.BytesIO()
    frames = [Image.new("RGB", (20, 20), c) for c in ("blue", "green")]
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:])

    result = normalize_image(out.getvalue())

    with Image.open(io.BytesIO(result.data)) as decoded:
        _, g, b = decoded.convert("RGB").getpixel((10, 10))  # type: ignore[misc]
        assert b > 200 and g < 60


def test_normalize_rejects_decompression_bombs() -> None:
    # A tiny file declaring 20000 x 20000 = 400 MP; must fail before decoding.
    bomb = image_bytes("PNG", (20000, 20000), mode="1")
    assert len(bomb) < 200_000
    with pytest.raises(InvalidImage):
        normalize_image(bomb)


@pytest.mark.parametrize("data", [b"\x89PNG\r\n\x1a\ntruncated", b"\xff\xd8\xff\xe0garbage", b""])
def test_normalize_rejects_broken_images(data: bytes) -> None:
    with pytest.raises(InvalidImage):
        normalize_image(data)


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("photo.jpg", "photo.jpg"),
        ("C:\\Users\\me\\作业.pdf", "作业.pdf"),
        ("../../etc/passwd", "passwd"),
        ("bad\r\nname\x00.txt", "badname.txt"),
        ("", "file"),
        (None, "file"),
        ("a" * 300, "a" * 255),
    ],
)
def test_clean_filename(raw: str | None, clean: str) -> None:
    assert clean_filename(raw) == clean
