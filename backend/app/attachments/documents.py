"""Text out of PDF and DOCX files (ADR 0008 §1). CPU-bound: call from a worker thread.

PDF pages with a text layer give their text directly; pages without one (scans) are
rendered to JPEG for the caller to hand to the vision model.
"""

import io
import re
import threading
import zipfile
from dataclasses import dataclass

import docx
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from docx.table import Table

MAX_PDF_PAGES = 50
# Fewer non-whitespace characters than this and a page counts as scanned: an image
# with at most a stray page number or watermark in its text layer.
MIN_PAGE_TEXT = 20
RENDER_DPI = 150
# Rendered pages are capped like uploaded images; this also stops a PDF declaring a
# 200-inch page from allocating a gigantic bitmap.
RENDER_MAX_EDGE = 1600
JPEG_QUALITY = 85
# Zip-bomb guard: the uncompressed Word XML we are willing to parse.
MAX_DOCX_XML_BYTES = 50 * 1024 * 1024

# PDFium is not thread-safe and pypdfium2 doesn't serialise calls, so every use of it
# in the process goes through this lock.
_PDFIUM_LOCK = threading.Lock()


class DocumentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PdfPage:
    number: int  # 1-based
    text: str | None  # set for pages with a text layer
    image: bytes | None  # JPEG, set for scanned pages


def split_pdf(data: bytes) -> list[PdfPage]:
    with _PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            if exc.err_code == pdfium_c.FPDF_ERR_PASSWORD:
                raise DocumentError("document_encrypted", "the PDF is password-protected") from exc
            raise DocumentError("document_unreadable", "the PDF could not be read") from exc
        try:
            if len(pdf) > MAX_PDF_PAGES:
                raise DocumentError(
                    "too_many_pages", f"PDFs can have at most {MAX_PDF_PAGES} pages"
                )
            return [_page(pdf, i) for i in range(len(pdf))]
        finally:
            pdf.close()


def _page(pdf: pdfium.PdfDocument, index: int) -> PdfPage:
    page = pdf[index]
    try:
        textpage = page.get_textpage()
        try:
            text = textpage.get_text_bounded()
        finally:
            textpage.close()
        if len(re.sub(r"\s", "", text)) >= MIN_PAGE_TEXT:
            return PdfPage(index + 1, text.replace("\r\n", "\n").strip(), None)
        width, height = page.get_size()  # points (1/72 inch)
        scale = min(RENDER_DPI / 72, RENDER_MAX_EDGE / max(width, height, 1))
        bitmap = page.render(scale=scale)
        try:
            image = bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()
        out = io.BytesIO()
        image.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return PdfPage(index + 1, None, out.getvalue())
    finally:
        page.close()


def docx_text(data: bytes) -> str:
    """Paragraphs and tables in document order; table cells joined with `|`."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
        if info.file_size > MAX_DOCX_XML_BYTES:
            raise DocumentError("document_unreadable", "the document is too large to read")
        document = docx.Document(io.BytesIO(data))
    except DocumentError:
        raise
    except Exception as exc:  # BadZipFile, KeyError, lxml errors, ...
        raise DocumentError("document_unreadable", "the document could not be read") from exc
    blocks: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in block.rows]
            blocks.append("\n".join(rows))
        elif block.text.strip():
            blocks.append(block.text)
    return "\n\n".join(blocks)
