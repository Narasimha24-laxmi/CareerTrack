import pytest

from conftest import PASSWORD


def test_register_creates_account_and_logs_in(client):
    response = client.post("/api/register", json={"email": "New@Example.com ", "password": PASSWORD})
    assert response.status_code == 201
    assert response.get_json()["user"]["email"] == "new@example.com"  # trimmed + lowercased
    assert client.get("/api/me").status_code == 200  # already logged in


def test_password_is_stored_hashed(app, client):
    client.post("/api/register", json={"email": "h@example.com", "password": PASSWORD})
    import sqlite3

    row = sqlite3.connect(app.config["DATABASE"]).execute(
        "SELECT password_hash FROM users WHERE email = 'h@example.com'"
    ).fetchone()
    assert row[0] != PASSWORD
    assert PASSWORD not in row[0]
    assert row[0].startswith(("scrypt:", "pbkdf2:"))


def test_duplicate_email_rejected(client, make_user):
    make_user("dup@example.com")
    response = client.post("/api/register", json={"email": "dup@example.com", "password": PASSWORD})
    assert response.status_code == 409
    assert "already exists" in response.get_json()["error"]


def test_duplicate_email_is_case_insensitive(client, make_user):
    make_user("case@example.com")
    response = client.post("/api/register", json={"email": "CASE@EXAMPLE.COM", "password": PASSWORD})
    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"email": "", "password": PASSWORD}, "enter your email"),
        ({"email": "not-an-email", "password": PASSWORD}, "valid email"),
        ({"email": "a@b", "password": PASSWORD}, "valid email"),
        ({"email": "ok@example.com", "password": ""}, "enter a password"),
        ({"email": "ok@example.com", "password": "short"}, "at least 8"),
        ({"email": "ok@example.com", "password": "x" * 200}, "too long"),
        ({"email": 123, "password": PASSWORD}, "enter your email"),
    ],
)
def test_register_validation(client, payload, message):
    response = client.post("/api/register", json=payload)
    assert response.status_code == 400
    assert message in response.get_json()["error"]


def test_login_success(app, make_user):
    make_user("login@example.com")
    fresh = app.test_client()
    fresh.environ_base["HTTP_X_REQUESTED_WITH"] = "CareerTrack"
    response = fresh.post("/api/login", json={"email": "LOGIN@example.com", "password": PASSWORD})
    assert response.status_code == 200
    assert fresh.get("/api/me").get_json()["user"]["email"] == "login@example.com"


def test_wrong_password_rejected(client, make_user):
    make_user("wrong@example.com")
    response = client.post("/api/login", json={"email": "wrong@example.com", "password": "Nope12345"})
    assert response.status_code == 401
    assert response.get_json()["error"] == "Incorrect email or password."


def test_unknown_email_gives_same_message(client):
    response = client.post("/api/login", json={"email": "ghost@example.com", "password": PASSWORD})
    assert response.status_code == 401
    assert response.get_json()["error"] == "Incorrect email or password."


def test_login_requires_both_fields(client):
    response = client.post("/api/login", json={"email": "a@example.com"})
    assert response.status_code == 400
    assert "email and password" in response.get_json()["error"]


def test_logout_ends_session(alice):
    assert alice.get("/api/me").status_code == 200
    assert alice.post("/api/logout").status_code == 200
    assert alice.get("/api/me").status_code == 401


def test_too_many_failed_logins_are_blocked(app, client, make_user):
    make_user("brute@example.com")
    for _ in range(app.config["LOGIN_MAX_FAILURES"]):
        assert client.post(
            "/api/login", json={"email": "brute@example.com", "password": "Wrong12345"}
        ).status_code == 401
    blocked = client.post("/api/login", json={"email": "brute@example.com", "password": PASSWORD})
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.get_json()["error"]


@pytest.mark.parametrize(
    "method, url",
    [
        ("get", "/api/me"),
        ("get", "/api/applications"),
        ("post", "/api/applications"),
        ("get", "/api/applications/1"),
        ("put", "/api/applications/1"),
        ("patch", "/api/applications/1/status"),
        ("delete", "/api/applications/1"),
        ("get", "/api/reminders"),
        ("get", "/api/stats"),
        ("post", "/api/match"),
    ],
)
def test_protected_endpoints_need_login(client, method, url):
    response = getattr(client, method)(url, json={})
    assert response.status_code == 401
    assert "log in" in response.get_json()["error"]
