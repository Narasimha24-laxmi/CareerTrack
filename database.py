"""SQLite helpers: one connection per request, schema created automatically."""
import os
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS applications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company        TEXT NOT NULL,
    role           TEXT NOT NULL,
    job_link       TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'Applied'
                   CHECK (status IN ('Applied', 'Interview', 'Offer', 'Rejected')),
    applied_date   TEXT,
    deadline       TEXT,
    interview_date TEXT,
    notes          TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_applications_user ON applications(user_id);
"""


def get_db():
    """Return this request's database connection (created on first use)."""
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(app):
    """Create the database file and tables if they do not exist yet."""
    folder = os.path.dirname(app.config["DATABASE"])
    if folder:
        os.makedirs(folder, exist_ok=True)
    with app.app_context():
        get_db().executescript(SCHEMA)
        get_db().commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    init_db(app)
