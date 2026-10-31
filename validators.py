"""Input validation. Every problem raises ValidationError with a plain-language message."""
import re
from datetime import date
from urllib.parse import urlparse

STATUSES = ("Applied", "Interview", "Offer", "Rejected")

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_LENGTHS = {"company": 100, "role": 100, "job_link": 500, "notes": 2000}


class ValidationError(Exception):
    """Raised when user input is not acceptable. `field` names the form field."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field


def validate_email(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Please enter your email address.", "email")
    email = value.strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise ValidationError("Please enter a valid email address.", "email")
    return email


def validate_password(value):
    if not isinstance(value, str) or not value:
        raise ValidationError("Please enter a password.", "password")
    if len(value) < 8:
        raise ValidationError("Password must be at least 8 characters long.", "password")
    if len(value) > 128:
        raise ValidationError("Password is too long (maximum 128 characters).", "password")
    return value


def parse_date(value, label, field):
    """Return an ISO date string (YYYY-MM-DD) or None when the value is blank."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    message = f"{label} must be a valid date (YYYY-MM-DD)."
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        raise ValidationError(message, field)
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:  # e.g. 2026-02-30
        raise ValidationError(message, field)
    if not 2000 <= parsed.year <= 2100:
        raise ValidationError(f"{label} must be between the years 2000 and 2100.", field)
    return parsed.isoformat()


def _clean_text(data, key, label, required=False):
    value = data.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be text.", key)
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{label} is required.", key)
    if len(value) > MAX_LENGTHS[key]:
        raise ValidationError(
            f"{label} is too long (maximum {MAX_LENGTHS[key]} characters).", key
        )
    return value


def validate_job_link(data):
    link = _clean_text(data, "job_link", "Job link")
    if not link:
        return ""
    parsed = urlparse(link)
    # Only http(s) links are allowed: blocks javascript: and data: URLs.
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValidationError(
            "Job link must start with http:// or https:// (for example https://company.com/jobs/1).",
            "job_link",
        )
    return link


def validate_status(value):
    if value is None or value == "":
        return "Applied"
    if value not in STATUSES:
        raise ValidationError(
            "Status must be one of: " + ", ".join(STATUSES) + ".", "status"
        )
    return value


def validate_application(data):
    """Validate a full application payload and return clean values for the database."""
    return {
        "company": _clean_text(data, "company", "Company", required=True),
        "role": _clean_text(data, "role", "Role", required=True),
        "job_link": validate_job_link(data),
        "status": validate_status(data.get("status")),
        "applied_date": parse_date(data.get("applied_date"), "Applied date", "applied_date"),
        "deadline": parse_date(data.get("deadline"), "Deadline", "deadline"),
        "interview_date": parse_date(
            data.get("interview_date"), "Interview date", "interview_date"
        ),
        "notes": _clean_text(data, "notes", "Notes"),
    }
