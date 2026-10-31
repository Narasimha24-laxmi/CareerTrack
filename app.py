"""CareerTrack - job application tracker with resume skill matching.

Run:  python app.py        (then open http://127.0.0.1:5000)
Test: pytest
"""
import importlib
import os
import secrets
import sqlite3
import time
from datetime import date, timedelta
from functools import wraps

from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

import database
import matcher
import reminders
import resume_reader
from validators import (
    STATUSES,
    ValidationError,
    parse_date,
    validate_application,
    validate_email,
    validate_password,
    validate_status,
)

MAX_JOB_TEXT = 20_000
MAX_RESUME_TEXT = 200_000

# Used so that "unknown email" and "wrong password" take similar time.
_DUMMY_HASH = generate_password_hash("not-a-real-password")

SERVER_ERROR_MESSAGE = "Something went wrong on our side. Please try again in a moment."

HTTP_MESSAGES = {
    400: "That request couldn't be understood.",
    401: "Please log in to continue.",
    403: "You don't have permission to do that.",
    404: "Not found.",
    405: "That action isn't supported here.",
    413: "The upload is too large. Resume files must be 2 MB or smaller.",
    429: "Too many attempts. Please wait a few minutes and try again.",
    500: SERVER_ERROR_MESSAGE,
}

APPLICATION_COLUMNS = (
    "id, company, role, job_link, status, applied_date, deadline, "
    "interview_date, notes, created_at, updated_at"
)


def _load_secret_key(app):
    """Secret key from the SECRET_KEY env var, else a random key saved in instance/."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = os.path.join(app.instance_path, ".secret_key")
    try:
        with open(path, encoding="utf-8") as handle:
            stored = handle.read().strip()
        if stored:
            return stored
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(key)
    return key


def warn_about_missing_packages(app):
    """Print a clear warning at startup if PDF/DOCX support is not installed."""
    missing = []
    for module, package in (("pypdf", "pypdf"), ("docx", "python-docx")):
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    if missing:
        app.logger.warning(
            "Missing package(s): %s. Resume upload will not work for those file types. "
            "Fix: pip install -r requirements.txt",
            ", ".join(missing),
        )


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, "careertrack.db"),
        MAX_CONTENT_LENGTH=3 * 1024 * 1024,  # whole request
        MAX_RESUME_BYTES=2 * 1024 * 1024,  # the resume file itself
        MAX_APPLICATIONS_PER_USER=1000,
        LOGIN_MAX_FAILURES=8,
        LOGIN_WINDOW_SECONDS=600,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("CAREERTRACK_HTTPS") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _load_secret_key(app)

    database.init_app(app)
    warn_about_missing_packages(app)
    app.extensions["login_failures"] = {}

    register_hooks(app)
    register_error_handlers(app)
    register_routes(app)
    return app


# --------------------------------------------------------------------------
# Hooks: CSRF guard and security headers
# --------------------------------------------------------------------------
def register_hooks(app):
    @app.before_request
    def require_ajax_header():
        # Browsers cannot add custom headers to cross-site form posts, so this
        # blocks CSRF on top of the SameSite cookie setting.
        if (
            request.path.startswith("/api/")
            and request.method in ("POST", "PUT", "PATCH", "DELETE")
            and request.headers.get("X-Requested-With") != "CareerTrack"
        ):
            return jsonify(error="Invalid request origin. Please reload the page."), 403

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


# --------------------------------------------------------------------------
# Error handling: always JSON, always plain language, never a stack trace
# --------------------------------------------------------------------------
def register_error_handlers(app):
    @app.errorhandler(ValidationError)
    def handle_validation(error):
        return jsonify(error=error.message, field=error.field), 400

    @app.errorhandler(resume_reader.ResumeReadError)
    def handle_resume(error):
        return jsonify(error=error.message, field="resume_file"), error.status

    @app.errorhandler(matcher.MatchError)
    def handle_match(error):
        return jsonify(error=str(error), field="job_description"), 400

    @app.errorhandler(HTTPException)
    def handle_http(error):
        message = HTTP_MESSAGES.get(error.code, "Something went wrong. Please try again.")
        return jsonify(error=message), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        app.logger.exception("Unhandled error: %s", error)
        return jsonify(error=SERVER_ERROR_MESSAGE), 500


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        if user_id is None:
            return jsonify(error=HTTP_MESSAGES[401]), 401
        user = database.get_db().execute(
            "SELECT id, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user is None:  # account deleted but cookie remains
            session.clear()
            return jsonify(error=HTTP_MESSAGES[401]), 401
        g.user = user
        return view(*args, **kwargs)

    return wrapped


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("The request must contain valid JSON.")
    return data


def get_owned_application(app_id):
    """Fetch an application ONLY if it belongs to the logged-in user, else 404.

    This is the single place that enforces per-user data isolation for
    reading, editing and deleting single records. A record that belongs to
    someone else is indistinguishable from one that does not exist.
    """
    row = database.get_db().execute(
        f"SELECT {APPLICATION_COLUMNS} FROM applications WHERE id = ? AND user_id = ?",
        (app_id, g.user["id"]),
    ).fetchone()
    if row is None:
        raise_not_found()
    return row


def raise_not_found():
    from werkzeug.exceptions import NotFound

    raise NotFound()


def row_to_dict(row):
    return {key: row[key] for key in row.keys()}


def request_today():
    """Today's date. The browser sends its local date so time zones are right."""
    raw = request.args.get("today")
    if raw:
        return date.fromisoformat(parse_date(raw, "Today's date", "today"))
    return date.today()


def user_payload(user):
    return {"id": user["id"], "email": user["email"]}


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
def register_routes(app):
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    # ---- Auth ----------------------------------------------------------
    @app.post("/api/register")
    def register():
        data = json_body()
        email = validate_email(data.get("email"))
        password = validate_password(data.get("password"))

        db = database.get_db()
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            return jsonify(error="An account with this email already exists.", field="email"), 409
        try:
            cursor = db.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(password)),
            )
            db.commit()
        except sqlite3.IntegrityError:  # two sign-ups at the same instant
            return jsonify(error="An account with this email already exists.", field="email"), 409

        session.clear()
        session["user_id"] = cursor.lastrowid
        session.permanent = True
        return jsonify(user={"id": cursor.lastrowid, "email": email}), 201

    @app.post("/api/login")
    def login():
        data = json_body()
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str) or not email or not password:
            raise ValidationError("Please enter your email and password.")
        email = email.strip().lower()

        failures = app.extensions["login_failures"]
        key = f"{request.remote_addr}|{email}"
        now = time.time()
        window = app.config["LOGIN_WINDOW_SECONDS"]
        recent = [t for t in failures.get(key, []) if now - t < window]
        failures[key] = recent
        if len(recent) >= app.config["LOGIN_MAX_FAILURES"]:
            return jsonify(error=HTTP_MESSAGES[429]), 429

        user = database.get_db().execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
        stored_hash = user["password_hash"] if user else _DUMMY_HASH
        valid = check_password_hash(stored_hash, password)
        if user is None or not valid:
            failures[key].append(now)
            return jsonify(error="Incorrect email or password."), 401

        failures.pop(key, None)
        session.clear()  # new session on login (prevents session fixation)
        session["user_id"] = user["id"]
        session.permanent = True
        return jsonify(user=user_payload(user))

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    @login_required
    def me():
        return jsonify(user=user_payload(g.user))

    # ---- Applications --------------------------------------------------
    @app.get("/api/applications")
    @login_required
    def list_applications():
        rows = database.get_db().execute(
            f"SELECT {APPLICATION_COLUMNS} FROM applications WHERE user_id = ? ORDER BY id DESC",
            (g.user["id"],),
        ).fetchall()
        return jsonify(applications=[row_to_dict(r) for r in rows])

    @app.post("/api/applications")
    @login_required
    def create_application():
        clean = validate_application(json_body())
        db = database.get_db()
        count = db.execute(
            "SELECT COUNT(*) FROM applications WHERE user_id = ?", (g.user["id"],)
        ).fetchone()[0]
        if count >= app.config["MAX_APPLICATIONS_PER_USER"]:
            raise ValidationError(
                f"You've reached the limit of {app.config['MAX_APPLICATIONS_PER_USER']} applications. "
                "Delete old ones to add more."
            )
        cursor = db.execute(
            """INSERT INTO applications
               (user_id, company, role, job_link, status, applied_date, deadline, interview_date, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                g.user["id"], clean["company"], clean["role"], clean["job_link"],
                clean["status"], clean["applied_date"], clean["deadline"],
                clean["interview_date"], clean["notes"],
            ),
        )
        db.commit()
        row = get_owned_application(cursor.lastrowid)
        return jsonify(application=row_to_dict(row)), 201

    @app.get("/api/applications/<int:app_id>")
    @login_required
    def get_application(app_id):
        return jsonify(application=row_to_dict(get_owned_application(app_id)))

    @app.put("/api/applications/<int:app_id>")
    @login_required
    def update_application(app_id):
        get_owned_application(app_id)  # 404 if not yours
        clean = validate_application(json_body())
        db = database.get_db()
        db.execute(
            """UPDATE applications
               SET company = ?, role = ?, job_link = ?, status = ?, applied_date = ?,
                   deadline = ?, interview_date = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND user_id = ?""",
            (
                clean["company"], clean["role"], clean["job_link"], clean["status"],
                clean["applied_date"], clean["deadline"], clean["interview_date"],
                clean["notes"], app_id, g.user["id"],
            ),
        )
        db.commit()
        return jsonify(application=row_to_dict(get_owned_application(app_id)))

    @app.patch("/api/applications/<int:app_id>/status")
    @login_required
    def update_status(app_id):
        get_owned_application(app_id)
        data = json_body()
        if not data.get("status"):
            raise ValidationError("Please choose a status.", "status")
        status = validate_status(data.get("status"))
        db = database.get_db()
        db.execute(
            "UPDATE applications SET status = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (status, app_id, g.user["id"]),
        )
        db.commit()
        return jsonify(application=row_to_dict(get_owned_application(app_id)))

    @app.delete("/api/applications/<int:app_id>")
    @login_required
    def delete_application(app_id):
        get_owned_application(app_id)
        db = database.get_db()
        db.execute(
            "DELETE FROM applications WHERE id = ? AND user_id = ?", (app_id, g.user["id"])
        )
        db.commit()
        return jsonify(ok=True)

    # ---- Reminders and stats ------------------------------------------
    @app.get("/api/reminders")
    @login_required
    def get_reminders():
        today = request_today()
        rows = database.get_db().execute(
            "SELECT id, company, role, status, deadline, interview_date "
            "FROM applications WHERE user_id = ?",
            (g.user["id"],),
        ).fetchall()
        result = reminders.build_reminders(rows, today)
        result["today"] = today.isoformat()
        return jsonify(result)

    @app.get("/api/stats")
    @login_required
    def get_stats():
        rows = database.get_db().execute(
            "SELECT status, COUNT(*) AS n FROM applications WHERE user_id = ? GROUP BY status",
            (g.user["id"],),
        ).fetchall()
        by_status = {status: 0 for status in STATUSES}
        for row in rows:
            by_status[row["status"]] = row["n"]
        total = sum(by_status.values())
        responded = by_status["Interview"] + by_status["Offer"] + by_status["Rejected"]
        response_rate = round(100 * responded / total, 1) if total else 0
        return jsonify(total=total, by_status=by_status, response_rate=response_rate)

    # ---- Resume matcher -------------------------------------------------
    @app.post("/api/match")
    @login_required
    def match():
        upload = None
        if request.mimetype == "multipart/form-data":
            job_text = request.form.get("job_description", "")
            resume_text = request.form.get("resume_text", "")
            upload = request.files.get("resume_file")
        else:
            data = json_body()
            job_text = data.get("job_description", "")
            resume_text = data.get("resume_text", "")

        if not isinstance(job_text, str) or not isinstance(resume_text, str):
            raise ValidationError("Resume and job description must be text.")
        job_text = job_text.strip()
        if not job_text:
            raise ValidationError("Please paste the job description.", "job_description")
        if len(job_text) > MAX_JOB_TEXT:
            raise ValidationError(
                f"The job description is too long (maximum {MAX_JOB_TEXT:,} characters).",
                "job_description",
            )

        source = "pasted text"
        if upload is not None and upload.filename:
            limit = app.config["MAX_RESUME_BYTES"]
            raw = upload.read(limit + 1)
            resume_text, source = resume_reader.extract_text(upload.filename, raw, limit)
        else:
            resume_text = resume_text.strip()
            if not resume_text:
                raise ValidationError(
                    "Please upload your resume or paste its text.", "resume_text"
                )
            if len(resume_text) > MAX_RESUME_TEXT:
                raise ValidationError(
                    f"The resume text is too long (maximum {MAX_RESUME_TEXT:,} characters).",
                    "resume_text",
                )

        result = matcher.match_resume(resume_text, job_text)
        result["resume_source"] = source
        result["resume_chars"] = len(resume_text)
        result["resume_preview"] = resume_text[:400]
        if result["resume_skill_count"] == 0:
            result["warning"] = (
                "We couldn't find any known skills in your resume text. "
                "If you uploaded a PDF, check that it contains selectable text."
            )
        return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    create_app().run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
