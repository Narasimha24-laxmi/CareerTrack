"""Resume upload: PDF, DOCX, TXT, plus every way a file can be bad."""
import io

from conftest import make_blank_pdf, make_docx, make_pdf

JOB = "Looking for React, Node.js, SQL and Docker skills."
READ_ERROR = "We couldn't read text from this file. Try a text-based PDF or paste your resume."


def upload(client, filename, data, job=JOB):
    return client.post(
        "/api/match",
        data={"job_description": job, "resume_file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


def test_valid_txt(alice):
    response = upload(alice, "resume.txt", b"I build apps with React and SQL.")
    assert response.status_code == 200
    body = response.get_json()
    assert body["matched_skills"] == ["React", "SQL"]
    assert body["resume_source"] == "resume.txt"


def test_valid_docx(alice):
    data = make_docx(["Jane Doe", "Skills: React, Node.js, Docker", "Experience with SQL databases"])
    response = upload(alice, "Jane Resume.docx", data)
    assert response.status_code == 200
    body = response.get_json()
    assert body["match_percent"] == 100
    assert body["resume_source"] == "Jane_Resume.docx"  # filename sanitized


def test_valid_pdf(alice):
    response = upload(alice, "resume.pdf", make_pdf("Skills React Docker Python"))
    assert response.status_code == 200
    body = response.get_json()
    assert body["matched_skills"] == ["React", "Docker"]
    assert body["extra_skills"] == ["Python"]
    assert "React" in body["resume_preview"]


def test_different_files_give_different_results(alice):
    a = upload(alice, "a.txt", b"React Node.js SQL Docker").get_json()
    b = upload(alice, "b.txt", b"Only Photoshop here").get_json()
    c = upload(alice, "c.pdf", make_pdf("React only")).get_json()
    assert (a["match_percent"], b["match_percent"], c["match_percent"]) == (100, 0, 25)


def test_uploaded_file_wins_over_pasted_text(alice):
    response = alice.post(
        "/api/match",
        data={
            "job_description": JOB,
            "resume_text": "React Node.js SQL Docker",
            "resume_file": (io.BytesIO(b"Photoshop"), "r.txt"),
        },
        content_type="multipart/form-data",
    )
    assert response.get_json()["match_percent"] == 0


def test_pasted_text_works_through_multipart_too(alice):
    response = alice.post(
        "/api/match",
        data={"job_description": JOB, "resume_text": "React and SQL"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200 and response.get_json()["match_percent"] == 50


def test_scanned_pdf_without_text(alice):
    response = upload(alice, "scan.pdf", make_blank_pdf())
    assert response.status_code == 400
    assert response.get_json()["error"] == READ_ERROR


def test_corrupted_pdf(alice):
    response = upload(alice, "broken.pdf", b"%PDF-1.4 this is not really a pdf at all")
    assert response.status_code == 400
    assert response.get_json()["error"] == READ_ERROR


def test_file_that_is_not_a_pdf_despite_extension(alice):
    response = upload(alice, "fake.pdf", b"just some text pretending")
    assert response.status_code == 400
    assert "valid PDF" in response.get_json()["error"]


def test_corrupted_docx(alice):
    response = upload(alice, "broken.docx", b"PK\x03\x04 definitely not a real docx")
    assert response.status_code == 400
    assert response.get_json()["error"] in (READ_ERROR, "That file doesn't look like a valid DOCX document.")


def test_wrong_extension_is_rejected(alice):
    for name in ("malware.exe", "resume.doc", "image.png", "noextension", "resume.pdf.exe"):
        response = upload(alice, name, b"React")
        assert response.status_code == 400, name
        assert "Unsupported file type" in response.get_json()["error"]


def test_empty_file(alice):
    response = upload(alice, "empty.txt", b"")
    assert response.status_code == 400
    assert "empty" in response.get_json()["error"]


def test_whitespace_only_text_file(alice):
    response = upload(alice, "blank.txt", b"   \n\n  ")
    assert response.status_code == 400
    assert response.get_json()["error"] == READ_ERROR


def test_oversized_file_over_resume_limit(alice):
    response = upload(alice, "big.txt", b"React " * 400_000)  # ~2.4 MB: under request cap, over file cap
    assert response.status_code == 413
    assert "2 MB or smaller" in response.get_json()["error"]


def test_oversized_request_is_rejected_by_server(alice):
    response = upload(alice, "huge.txt", b"a" * (4 * 1024 * 1024))
    assert response.status_code == 413
    assert "2 MB or smaller" in response.get_json()["error"]


def test_binary_file_named_txt(alice):
    response = upload(alice, "binary.txt", b"abc\x00\x01\x02def")
    assert response.status_code == 400


def test_non_utf8_text_file(alice):
    response = upload(alice, "latin.txt", "Skills: React, SQL, caf\xe9".encode("cp1252"))
    assert response.status_code == 200
    assert response.get_json()["matched_skills"] == ["React", "SQL"]


def test_upload_requires_login(client):
    assert upload(client, "r.txt", b"React").status_code == 401


def test_files_are_not_saved_on_the_server(app, alice, tmp_path):
    upload(alice, "resume.txt", b"React SQL")
    import os

    for root, _dirs, files in os.walk(os.path.dirname(app.config["DATABASE"])):
        assert not any(f.endswith((".txt", ".pdf", ".docx")) for f in files)


# ---- setup problems and unexpected failures must never be a vague server error ----
def test_missing_pdf_library_gives_clear_message(alice, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "pypdf", None)  # makes "import pypdf" fail, like an uninstalled package
    response = upload(alice, "resume.pdf", make_pdf("React"))
    assert response.status_code == 503
    body = response.get_json()
    assert "'pypdf' package is not installed" in body["error"]
    assert "pip install -r requirements.txt" in body["error"]
    assert body["field"] == "resume_file"


def test_missing_docx_library_gives_clear_message(alice, monkeypatch):
    import sys

    data = make_docx(["React"])  # build the sample file first, while python-docx still works
    monkeypatch.setitem(sys.modules, "docx", None)
    response = upload(alice, "resume.docx", data)
    assert response.status_code == 503
    assert "'python-docx' package is not installed" in response.get_json()["error"]


def test_missing_library_does_not_break_txt_or_pasted_text(alice, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "pypdf", None)
    assert upload(alice, "resume.txt", b"React and SQL").status_code == 200
    pasted = alice.post("/api/match", json={"resume_text": "React", "job_description": JOB})
    assert pasted.status_code == 200


def test_unexpected_reader_crash_is_not_a_server_error(alice, monkeypatch):
    import resume_reader

    def boom(_data):
        raise RuntimeError("something odd inside the file")

    monkeypatch.setattr(resume_reader, "_read_txt", boom)
    response = upload(alice, "resume.txt", b"React")
    assert response.status_code == 400
    assert response.get_json()["error"] == READ_ERROR


def test_startup_warns_when_packages_are_missing(app, monkeypatch, caplog):
    import sys

    import app as app_module

    monkeypatch.setitem(sys.modules, "pypdf", None)
    with caplog.at_level("WARNING"):
        app_module.warn_about_missing_packages(app)
    assert "Missing package(s): pypdf" in caplog.text
    assert "pip install -r requirements.txt" in caplog.text
