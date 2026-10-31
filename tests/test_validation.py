"""Invalid input and server failures must produce clear messages, never crashes."""
import sqlite3

import pytest

import database
import reminders
from conftest import sample_application


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"company": ""}, "Company is required."),
        ({"company": "   "}, "Company is required."),
        ({"role": ""}, "Role is required."),
        ({"company": "x" * 101}, "Company is too long"),
        ({"company": 42}, "Company must be text."),
        ({"notes": "n" * 2001}, "Notes is too long"),
        ({"status": "Ghosted"}, "Status must be one of"),
        ({"deadline": "2026-02-30"}, "Deadline must be a valid date (YYYY-MM-DD)."),
        ({"deadline": "tomorrow"}, "Deadline must be a valid date (YYYY-MM-DD)."),
        ({"deadline": "10/11/2026"}, "Deadline must be a valid date (YYYY-MM-DD)."),
        ({"deadline": "2026-1-5"}, "Deadline must be a valid date (YYYY-MM-DD)."),
        ({"applied_date": "2026-13-01"}, "Applied date must be a valid date"),
        ({"interview_date": "abc"}, "Interview date must be a valid date"),
        ({"deadline": "1850-01-01"}, "between the years"),
        ({"job_link": "company.com/jobs"}, "Job link must start with http"),
        ({"job_link": "ftp://example.com"}, "Job link must start with http"),
        ({"job_link": "https://"}, "Job link must start with http"),
    ],
)
def test_create_rejects_invalid_input(alice, overrides, message):
    response = alice.post("/api/applications", json=sample_application(**overrides))
    assert response.status_code == 400
    assert message in response.get_json()["error"]
    assert alice.get("/api/applications").get_json()["applications"] == []  # nothing saved


def test_error_names_the_field_for_the_form(alice):
    body = alice.post("/api/applications", json=sample_application(deadline="nope")).get_json()
    assert body["field"] == "deadline"


def test_update_validates_too(alice):
    record = alice.post("/api/applications", json=sample_application()).get_json()["application"]
    response = alice.put(f"/api/applications/{record['id']}", json=sample_application(company=""))
    assert response.status_code == 400
    assert alice.get(f"/api/applications/{record['id']}").get_json()["application"]["company"] == "Google"


def test_status_change_validation(alice):
    record = alice.post("/api/applications", json=sample_application()).get_json()["application"]
    url = f"/api/applications/{record['id']}/status"
    assert alice.patch(url, json={"status": "Nope"}).status_code == 400
    assert alice.patch(url, json={}).status_code == 400
    ok = alice.patch(url, json={"status": "Interview"})
    assert ok.status_code == 200 and ok.get_json()["application"]["status"] == "Interview"


def test_valid_application_roundtrip(alice):
    created = alice.post("/api/applications", json=sample_application(interview_date="2026-11-12")).get_json()["application"]
    assert created["company"] == "Google"
    assert created["interview_date"] == "2026-11-12"
    updated = alice.put(
        f"/api/applications/{created['id']}",
        json=sample_application(company="Alphabet", status="Interview", deadline=""),
    ).get_json()["application"]
    assert updated["company"] == "Alphabet" and updated["status"] == "Interview" and updated["deadline"] is None
    assert alice.delete(f"/api/applications/{created['id']}").status_code == 200
    assert alice.get(f"/api/applications/{created['id']}").status_code == 404


def test_malformed_json_gives_clear_message(alice):
    response = alice.post("/api/applications", data="{not json", content_type="application/json")
    assert response.status_code == 400
    assert "valid JSON" in response.get_json()["error"]


def test_json_array_instead_of_object(alice):
    response = alice.post("/api/applications", json=[1, 2, 3])
    assert response.status_code == 400


def test_unknown_route_and_wrong_method_return_json(alice):
    missing = alice.get("/api/does-not-exist")
    assert missing.status_code == 404 and missing.get_json() == {"error": "Not found."}
    wrong = alice.delete("/api/applications")
    assert wrong.status_code == 405 and "error" in wrong.get_json()


def test_non_numeric_id_is_not_found(alice):
    assert alice.get("/api/applications/abc").status_code == 404


def test_application_limit_per_user(app, alice):
    app.config["MAX_APPLICATIONS_PER_USER"] = 2
    for _ in range(2):
        assert alice.post("/api/applications", json=sample_application()).status_code == 201
    response = alice.post("/api/applications", json=sample_application())
    assert response.status_code == 400
    assert "limit of 2" in response.get_json()["error"]


# ---- server failures -------------------------------------------------------
def test_unexpected_bug_returns_friendly_500(alice, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("secret internal detail /etc/passwd")

    monkeypatch.setattr(reminders, "build_reminders", explode)
    response = alice.get("/api/reminders")
    assert response.status_code == 500
    text = response.get_data(as_text=True)
    assert "Something went wrong on our side" in text
    assert "secret internal detail" not in text
    assert "Traceback" not in text


def test_database_outage_returns_friendly_500(alice, monkeypatch):
    def broken_db():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(database, "get_db", broken_db)
    response = alice.get("/api/applications")
    assert response.status_code == 500
    assert response.get_json() == {"error": "Something went wrong on our side. Please try again in a moment."}
    login = alice.post("/api/login", json={"email": "alice@example.com", "password": "Password123"})
    assert login.status_code == 500 and "Something went wrong" in login.get_json()["error"]


def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"CareerTrack" in response.data
