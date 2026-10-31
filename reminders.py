"""Deadline / interview reminders, computed from a date (today) passed in by the caller.

Buckets: overdue (before today), today, upcoming (1-7 days away), later (8+ days).
Applications that are already Offer or Rejected are finished, so they never remind.
"""
from datetime import date

UPCOMING_DAYS = 7
ACTIVE_STATUSES = ("Applied", "Interview")


def classify(due, today):
    """Return (bucket, days_left) for a due date compared with today."""
    days_left = (due - today).days
    if days_left < 0:
        return "overdue", days_left
    if days_left == 0:
        return "today", 0
    if days_left <= UPCOMING_DAYS:
        return "upcoming", days_left
    return "later", days_left


def describe(bucket, days_left):
    if bucket == "overdue":
        n = abs(days_left)
        return f"{n} day{'s' if n != 1 else ''} overdue"
    if bucket == "today":
        return "Due today"
    if days_left == 1:
        return "Tomorrow"
    return f"In {days_left} days"


def build_reminders(rows, today):
    """Build the reminder list for a user's application rows.

    Returns {"counts": {...}, "items": [...]}. `items` holds overdue, today and
    upcoming entries sorted by date; "later" entries are only counted.
    """
    counts = {"overdue": 0, "today": 0, "upcoming": 0, "later": 0}
    items = []
    for row in rows:
        if row["status"] not in ACTIVE_STATUSES:
            continue
        for kind, field in (("Deadline", "deadline"), ("Interview", "interview_date")):
            raw = row[field]
            if not raw:
                continue
            try:
                due = date.fromisoformat(raw)
            except ValueError:  # bad data should never crash the dashboard
                continue
            bucket, days_left = classify(due, today)
            counts[bucket] += 1
            if bucket == "later":
                continue
            items.append(
                {
                    "application_id": row["id"],
                    "company": row["company"],
                    "role": row["role"],
                    "kind": kind,
                    "date": raw,
                    "bucket": bucket,
                    "days_left": days_left,
                    "label": describe(bucket, days_left),
                }
            )
    items.sort(key=lambda item: (item["date"], item["application_id"], item["kind"]))
    return {"counts": counts, "items": items}
