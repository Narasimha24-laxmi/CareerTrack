"""Extract plain text from an uploaded resume (PDF, DOCX or TXT).

Files are processed in memory only; nothing is saved to disk.
"""
import io
import logging
import os
import zipfile

from werkzeug.utils import secure_filename

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = (".pdf", ".docx", ".txt")
MAX_PDF_PAGES = 30
MAX_TEXT_CHARS = 200_000
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024  # guards against zip bombs

UNREADABLE = "We couldn't read text from this file. Try a text-based PDF or paste your resume."


class ResumeReadError(Exception):
    """A problem with the uploaded file, written for the end user."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _missing_library(package):
    """Error for a reader library that isn't installed (a setup problem, not a user mistake)."""
    log.error("The '%s' package is not installed. Run: pip install -r requirements.txt", package)
    return ResumeReadError(
        f"This server can't read that file type yet because the '{package}' package is not installed. "
        "Paste your resume text instead, or run: pip install -r requirements.txt and restart the app.",
        503,
    )


def _read_pdf(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise _missing_library("pypdf")

    if b"%PDF" not in data[:1024]:
        raise ResumeReadError("That file doesn't look like a valid PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                raise ResumeReadError(
                    "This PDF is password-protected. Remove the password or paste your resume text."
                )
        pages = reader.pages[:MAX_PDF_PAGES]
        return "\n".join((page.extract_text() or "") for page in pages)
    except ResumeReadError:
        raise
    except Exception:
        raise ResumeReadError(UNREADABLE)


def _read_docx(data):
    try:
        from docx import Document
    except ImportError:
        raise _missing_library("python-docx")

    buffer = io.BytesIO(data)
    if not zipfile.is_zipfile(buffer):
        raise ResumeReadError("That file doesn't look like a valid DOCX document.")
    try:
        with zipfile.ZipFile(buffer) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_DOCX_UNCOMPRESSED:
                raise ResumeReadError("That document is too large to read.")
        document = Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text)
        return "\n".join(parts)
    except ResumeReadError:
        raise
    except Exception:
        raise ResumeReadError(UNREADABLE)


def _read_txt(data):
    if b"\x00" in data:
        raise ResumeReadError("That doesn't look like a plain text file.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def extract_text(filename, data, max_bytes):
    """Return (text, display_name) for an uploaded resume, or raise ResumeReadError."""
    extension = os.path.splitext(filename or "")[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ResumeReadError("Unsupported file type. Please upload a PDF, DOCX or TXT file.")
    if not data:
        raise ResumeReadError("That file is empty.")
    if len(data) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise ResumeReadError(f"That file is too large. Resume files must be {mb} MB or smaller.", 413)

    reader = {".pdf": _read_pdf, ".docx": _read_docx, ".txt": _read_txt}[extension]
    try:
        text = reader(data)
    except ResumeReadError:
        raise
    except Exception:
        # Safety net: a problem inside a file must never turn into a server error.
        log.exception("Unexpected error while reading an uploaded %s file", extension)
        raise ResumeReadError(UNREADABLE)
    text = " ".join(text.split())  # collapse whitespace and line breaks
    if not text:
        raise ResumeReadError(UNREADABLE)

    display_name = secure_filename(filename) or ("resume" + extension)
    return text[:MAX_TEXT_CHARS], display_name
