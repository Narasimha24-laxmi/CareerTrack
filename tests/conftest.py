import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

PASSWORD = "Password123"


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "test.db"),
        }
    )


def _client(app):
    client = app.test_client()
    client.environ_base["HTTP_X_REQUESTED_WITH"] = "CareerTrack"
    return client


@pytest.fixture
def client(app):
    """A logged-out browser."""
    return _client(app)


@pytest.fixture
def make_user(app):
    """Factory: registers a user and returns a logged-in client (own cookie jar)."""

    def factory(email):
        c = _client(app)
        response = c.post("/api/register", json={"email": email, "password": PASSWORD})
        assert response.status_code == 201, response.get_json()
        return c

    return factory


@pytest.fixture
def alice(make_user):
    return make_user("alice@example.com")


@pytest.fixture
def bob(make_user):
    return make_user("bob@example.com")


def sample_application(**overrides):
    data = {
        "company": "Google",
        "role": "Frontend Intern",
        "job_link": "https://careers.google.com/jobs/1",
        "status": "Applied",
        "applied_date": "2026-10-01",
        "deadline": "2026-11-10",
        "interview_date": "",
        "notes": "Referral from a senior.",
    }
    data.update(overrides)
    return data


# ---- helpers to build real files for upload tests ------------------------
def make_pdf(text):
    """Build a tiny but valid one-page PDF that contains `text`."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_at).encode() + b"\n%%EOF"
    )
    return out


def make_blank_pdf():
    """A PDF with a page but no text (what a scanned resume looks like)."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_docx(paragraphs):
    from docx import Document

    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
