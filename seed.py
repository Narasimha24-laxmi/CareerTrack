"""Create two demo users with sample applications.

Run:  python seed.py
Log in with:
    demo1@careertrack.dev / Demo@1234
    demo2@careertrack.dev / Demo@1234
Dates are relative to today, so overdue / today / upcoming reminders always show.
"""
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

import database
from app import create_app

DEMO_PASSWORD = "Demo@1234"


def iso(offset_days):
    return (date.today() + timedelta(days=offset_days)).isoformat()


# (company, role, link, status, applied offset, deadline offset, interview offset, notes)
DEMO_DATA = {
    "demo1@careertrack.dev": [
        ("Google", "Frontend Intern", "https://careers.google.com", "Applied", -5, -2, None, "Referral from college senior."),
        ("Microsoft", "Software Engineer Intern", "https://careers.microsoft.com", "Applied", -3, 0, None, "Submit coding test today."),
        ("Flipkart", "SDE Intern", "https://www.flipkartcareers.com", "Interview", -12, None, 3, "Round 1: DSA. Revise trees and graphs."),
        ("Walmart", "Data Analyst Intern", "https://careers.walmart.com", "Applied", -1, 6, None, ""),
        ("Zoho", "Web Developer", "https://www.zoho.com/careers", "Offer", -30, None, None, "Offer letter received."),
        ("Infosys", "Systems Engineer", "https://www.infosys.com/careers", "Rejected", -25, None, None, "Did not clear aptitude round."),
        ("Swiggy", "Backend Intern", "https://careers.swiggy.com", "Applied", 0, 20, None, "Prepare Flask and SQL projects."),
    ],
    "demo2@careertrack.dev": [
        ("Amazon", "SDE Intern", "https://www.amazon.jobs", "Interview", -10, None, 1, "Online assessment passed."),
        ("TCS", "Digital Associate", "https://www.tcs.com/careers", "Applied", -4, -1, None, ""),
        ("Razorpay", "Frontend Intern", "https://razorpay.com/jobs", "Applied", -2, 4, None, "Customize resume for fintech."),
    ],
}


def seed():
    app = create_app()
    with app.app_context():
        db = database.get_db()
        for email, applications in DEMO_DATA.items():
            db.execute("DELETE FROM users WHERE email = ?", (email,))  # cascades to applications
            cursor = db.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(DEMO_PASSWORD)),
            )
            user_id = cursor.lastrowid
            for company, role, link, status, applied, deadline, interview, notes in applications:
                db.execute(
                    """INSERT INTO applications
                       (user_id, company, role, job_link, status, applied_date, deadline, interview_date, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id, company, role, link, status, iso(applied),
                        iso(deadline) if deadline is not None else None,
                        iso(interview) if interview is not None else None,
                        notes,
                    ),
                )
        db.commit()
    print("Demo data created.")
    for email in DEMO_DATA:
        print(f"  {email}  /  {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
