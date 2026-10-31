"""Data isolation: one user must never reach another user's records."""
from conftest import sample_application


def create(client, **overrides):
    response = client.post("/api/applications", json=sample_application(**overrides))
    assert response.status_code == 201, response.get_json()
    return response.get_json()["application"]


def test_user_cannot_read_another_users_application(alice, bob):
    record = create(alice)
    response = bob.get(f"/api/applications/{record['id']}")
    assert response.status_code == 404
    assert response.get_json() == {"error": "Not found."}


def test_user_cannot_edit_another_users_application(alice, bob):
    record = create(alice, company="Alice Corp")
    response = bob.put(
        f"/api/applications/{record['id']}", json=sample_application(company="Hacked")
    )
    assert response.status_code == 404
    assert alice.get(f"/api/applications/{record['id']}").get_json()["application"]["company"] == "Alice Corp"


def test_user_cannot_change_status_of_another_users_application(alice, bob):
    record = create(alice)
    response = bob.patch(f"/api/applications/{record['id']}/status", json={"status": "Rejected"})
    assert response.status_code == 404
    assert alice.get(f"/api/applications/{record['id']}").get_json()["application"]["status"] == "Applied"


def test_user_cannot_delete_another_users_application(alice, bob):
    record = create(alice)
    assert bob.delete(f"/api/applications/{record['id']}").status_code == 404
    assert alice.get(f"/api/applications/{record['id']}").status_code == 200


def test_lists_only_show_own_records(alice, bob):
    create(alice, company="Alice Corp")
    create(bob, company="Bob Inc")
    alice_companies = [a["company"] for a in alice.get("/api/applications").get_json()["applications"]]
    bob_companies = [a["company"] for a in bob.get("/api/applications").get_json()["applications"]]
    assert alice_companies == ["Alice Corp"]
    assert bob_companies == ["Bob Inc"]


def test_stats_and_reminders_are_per_user(alice, bob):
    create(alice, deadline="2026-10-28")
    create(alice, deadline="2026-10-28")
    create(bob, deadline="2026-10-28")
    assert alice.get("/api/stats").get_json()["total"] == 2
    assert bob.get("/api/stats").get_json()["total"] == 1
    alice_items = alice.get("/api/reminders?today=2026-10-29").get_json()["items"]
    bob_items = bob.get("/api/reminders?today=2026-10-29").get_json()["items"]
    assert len(alice_items) == 2
    assert len(bob_items) == 1


def test_other_users_record_looks_identical_to_missing_record(alice, bob):
    record = create(alice)
    not_yours = bob.get(f"/api/applications/{record['id']}")
    missing = bob.get("/api/applications/999999")
    assert not_yours.status_code == missing.status_code == 404
    assert not_yours.get_json() == missing.get_json()  # no information leak


def test_sql_injection_is_stored_as_plain_text(alice, bob):
    payload = "x'); DROP TABLE applications; --"
    record = create(alice, company=payload)
    fetched = alice.get(f"/api/applications/{record['id']}").get_json()["application"]
    assert fetched["company"] == payload
    assert alice.get("/api/applications").status_code == 200  # table still exists


def test_sql_injection_in_login_does_not_bypass_auth(client, make_user):
    make_user("victim@example.com")
    response = client.post("/api/login", json={"email": "victim@example.com' OR '1'='1", "password": "x' OR '1'='1"})
    assert response.status_code == 401
    assert client.get("/api/me").status_code == 401


def test_javascript_links_are_rejected(alice):
    response = alice.post("/api/applications", json=sample_application(job_link="javascript:alert(1)"))
    assert response.status_code == 400
    assert "http://" in response.get_json()["error"]


def test_html_in_text_is_stored_verbatim_for_the_ui_to_escape(alice):
    record = create(alice, company="<script>alert(1)</script>")
    assert record["company"] == "<script>alert(1)</script>"  # the UI renders it with textContent


def test_requests_without_csrf_header_are_blocked(app, alice):
    raw = app.test_client()  # no X-Requested-With header
    raw.post("/api/login", json={"email": "alice@example.com", "password": "Password123"})
    response = raw.post("/api/applications", json=sample_application())
    assert response.status_code == 403
    assert "Invalid request origin" in response.get_json()["error"]


def test_security_headers_present(client):
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
