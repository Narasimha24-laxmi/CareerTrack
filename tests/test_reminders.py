from datetime import date

from conftest import sample_application
from reminders import build_reminders, classify

TODAY = date(2026, 10, 29)


def row(id=1, status="Applied", deadline=None, interview_date=None, company="Acme", role="Dev"):
    return {
        "id": id, "status": status, "deadline": deadline,
        "interview_date": interview_date, "company": company, "role": role,
    }


def test_classify_buckets_with_fixed_dates():
    assert classify(date(2026, 10, 28), TODAY) == ("overdue", -1)
    assert classify(date(2026, 10, 1), TODAY) == ("overdue", -28)
    assert classify(date(2026, 10, 29), TODAY) == ("today", 0)
    assert classify(date(2026, 10, 30), TODAY) == ("upcoming", 1)
    assert classify(date(2026, 11, 5), TODAY) == ("upcoming", 7)  # 7 days is still upcoming
    assert classify(date(2026, 11, 6), TODAY) == ("later", 8)  # 8 days is later


def test_classify_across_month_and_year_boundaries():
    assert classify(date(2026, 11, 1), date(2026, 10, 31)) == ("upcoming", 1)
    assert classify(date(2027, 1, 2), date(2026, 12, 31)) == ("upcoming", 2)
    assert classify(date(2028, 2, 29), date(2028, 2, 28)) == ("upcoming", 1)  # leap day
    assert classify(date(2026, 12, 31), date(2027, 1, 1)) == ("overdue", -1)


def test_build_reminders_groups_and_sorts():
    rows = [
        row(1, deadline="2026-11-03"),                     # upcoming
        row(2, deadline="2026-10-27"),                     # overdue
        row(3, deadline="2026-10-29"),                     # today
        row(4, deadline="2026-12-25"),                     # later (counted only)
        row(5, status="Interview", interview_date="2026-10-30"),  # upcoming
    ]
    result = build_reminders(rows, TODAY)
    assert result["counts"] == {"overdue": 1, "today": 1, "upcoming": 2, "later": 1}
    assert [(i["application_id"], i["bucket"]) for i in result["items"]] == [
        (2, "overdue"), (3, "today"), (5, "upcoming"), (1, "upcoming"),
    ]


def test_labels_are_human_readable():
    rows = [
        row(1, deadline="2026-10-27"),
        row(2, deadline="2026-10-28"),
        row(3, deadline="2026-10-29"),
        row(4, deadline="2026-10-30"),
        row(5, deadline="2026-11-02"),
    ]
    labels = {i["application_id"]: i["label"] for i in build_reminders(rows, TODAY)["items"]}
    assert labels == {
        1: "2 days overdue", 2: "1 day overdue", 3: "Due today", 4: "Tomorrow", 5: "In 4 days",
    }


def test_finished_applications_do_not_remind():
    rows = [
        row(1, status="Offer", deadline="2026-10-01"),
        row(2, status="Rejected", interview_date="2026-10-01"),
    ]
    result = build_reminders(rows, TODAY)
    assert result["items"] == []
    assert result["counts"] == {"overdue": 0, "today": 0, "upcoming": 0, "later": 0}


def test_missing_and_corrupt_dates_are_skipped():
    rows = [row(1, deadline=None), row(2, deadline=""), row(3, deadline="garbage")]
    assert build_reminders(rows, TODAY)["items"] == []


def test_one_application_can_have_deadline_and_interview():
    result = build_reminders([row(1, status="Interview", deadline="2026-10-20", interview_date="2026-10-31")], TODAY)
    assert [(i["kind"], i["bucket"]) for i in result["items"]] == [("Deadline", "overdue"), ("Interview", "upcoming")]


# ---- through the HTTP API ---------------------------------------------------
def test_api_reminders_use_the_date_given(alice):
    for deadline in ("2026-10-28", "2026-10-29", "2026-11-04", "2026-12-31"):
        alice.post("/api/applications", json=sample_application(deadline=deadline))
    body = alice.get("/api/reminders?today=2026-10-29").get_json()
    assert body["today"] == "2026-10-29"
    assert body["counts"] == {"overdue": 1, "today": 1, "upcoming": 1, "later": 1}

    # The same data looks different on another day: the result is computed, not stored.
    later = alice.get("/api/reminders?today=2026-11-10").get_json()
    assert later["counts"] == {"overdue": 3, "today": 0, "upcoming": 0, "later": 1}


def test_api_reminders_default_to_server_today(alice):
    body = alice.get("/api/reminders").get_json()
    assert body["today"] == date.today().isoformat()


def test_api_reminders_reject_bad_today(alice):
    response = alice.get("/api/reminders?today=yesterday")
    assert response.status_code == 400
    assert "valid date" in response.get_json()["error"]


def test_moving_to_offer_clears_reminder(alice):
    created = alice.post("/api/applications", json=sample_application(deadline="2026-10-28")).get_json()["application"]
    assert alice.get("/api/reminders?today=2026-10-29").get_json()["counts"]["overdue"] == 1
    alice.patch(f"/api/applications/{created['id']}/status", json={"status": "Offer"})
    assert alice.get("/api/reminders?today=2026-10-29").get_json()["counts"]["overdue"] == 0
