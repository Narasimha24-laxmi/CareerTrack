# CareerTrack

A job and internship application tracker with resume skill matching, built for students.

Add every application to one dashboard, see what is overdue or due soon, move applications across a
Kanban board (Applied, Interview, Offer, Rejected), and check how well your resume matches a job
description. Upload a PDF, DOCX or TXT resume, or paste the text.

**Stack:** Python 3 + Flask, SQLite, plain HTML/CSS/JavaScript (no build step, no external services, no API keys).

## Features

| Area | What it does |
|---|---|
| Accounts | Register, log in, log out. Passwords are hashed. Sessions last 7 days. |
| Applications | Add, edit, delete. Fields: company, role, job link, status, applied date, deadline, interview date, notes. |
| Kanban board | Four columns. Move a card by dragging it or with the status dropdown (works on phones and keyboards). Search by company or role. |
| Reminders | Deadlines and interviews are labelled **Overdue**, **Due today**, **Upcoming** (next 7 days) or later, calculated from today's date in your browser. Offers and rejections never remind. |
| Resume matcher | Reads your resume (uploaded file or pasted text) and the job description, finds skills in both, and shows a match percentage, skills you have, skills to add, and extra skills. |
| Stats | Total applications, count per status, response rate. |

## Quick start

You need Python 3.9 or newer.

```bash
cd careertrack

# 1. (recommended) create a virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. install the libraries
pip install -r requirements.txt

# 3. (optional) create two demo users with sample data
python seed.py

# 4. run the app
python app.py
```

Open **http://127.0.0.1:5000**.

Demo logins (only after `python seed.py`): `demo1@careertrack.dev` or `demo2@careertrack.dev`, password `Demo@1234`.
The demo dates are relative to today, so overdue, due-today and upcoming reminders always appear.

The database file is created automatically in `instance/careertrack.db`. To reset everything, stop the app and delete the `instance/` folder.

## Run the tests

```bash
pytest
```

121 automated tests cover each requirement:

| File | Proves |
|---|---|
| `tests/test_security.py` | User A cannot read, edit, delete or list User B's records (always `404 Not found.`), SQL injection is harmless, `javascript:` links are blocked, CSRF header is required. |
| `tests/test_matcher.py` | The matcher works on the real text: different resumes and job descriptions give different results, whole-word matching (`java` is not found inside `javascript`), aliases, `C++`, `.NET`, `Node.js`. |
| `tests/test_reminders.py` | Overdue, today, upcoming and later are classified correctly using fixed dates, including month, year and leap-day boundaries. |
| `tests/test_validation.py` | Invalid input returns a clear message and the right status code. Server and database failures return a friendly message with no stack trace. |
| `tests/test_upload.py` | Valid PDF, DOCX and TXT work. Scanned PDF, corrupted file, wrong type, empty file and oversized file all return clear messages. |
| `tests/test_auth.py` | Registration, duplicate email, wrong password, logout, login throttling, and every protected endpoint requires login. |

## Project structure

```
careertrack/
  app.py              Flask app: routes, error handlers, security headers
  database.py         SQLite connection and table creation
  validators.py       Input validation (plain-language error messages)
  matcher.py          Skill dictionary and resume-to-job matching
  reminders.py        Overdue / today / upcoming logic
  resume_reader.py    Text extraction from PDF, DOCX, TXT (in memory)
  seed.py             Demo users and sample data
  wsgi.py             Entry point for production servers
  templates/index.html
  static/css/style.css, static/js/app.js
  tests/              pytest suite
```

## How the main parts work

**Data isolation.** Every query that touches an application includes `AND user_id = <logged-in user>`.
Single-record access goes through one function, `get_owned_application()`, which returns `404 Not found.`
when the record does not exist *or* belongs to someone else. Both cases look identical, so nobody can
discover that another user's record exists.

**Resume matcher.** `matcher.py` holds 91 skills (166 spellings in total), each with aliases (`js` = JavaScript,
`k8s` = Kubernetes). It scans the text for whole-word matches, longest alias first, then compares the
job's skills with the resume's skills: `match % = matched skills / skills the job asks for`.
It is rule-based, not AI, so the same input always gives the same output and it needs no API key.

**Reminders.** `reminders.py` compares each date with a "today" value. The browser sends its own local
date, so the labels are right in every time zone. Tests pass fixed dates, so they never break as time passes.

**Errors.** Every error is JSON with a plain-language `error` message, and the page shows it next to
the field that caused it. Unexpected failures are logged on the server and the user only sees
"Something went wrong on our side. Please try again in a moment."

**Security measures.** Hashed passwords, HTTP-only same-site session cookies, a required
`X-Requested-With` header on every change request (CSRF), parameterized SQL, all user text inserted
with `textContent` (no XSS), a strict Content-Security-Policy, only `http(s)` job links, login
throttling (8 failed attempts per 10 minutes), request size limits, uploads processed in memory and never saved.

## Configuration

| Environment variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs login cookies. If unset, a random key is created once and saved in `instance/.secret_key`. Set it explicitly in production. |
| `PORT` | Port for `python app.py` (default 5000). |
| `CAREERTRACK_HTTPS=1` | Marks the session cookie as Secure. Set this when serving over HTTPS. |
| `FLASK_DEBUG=1` | Developer mode (never use in production). |

## Deploying (optional)

Any host that runs Python works. Example for Render or similar:

- Build command: `pip install -r requirements.txt gunicorn`
- Start command: `gunicorn wsgi:app`
- Environment: `SECRET_KEY=<long random string>`, `CAREERTRACK_HTTPS=1`

Note: free hosting tiers usually have a temporary disk, so the SQLite file resets when the service
restarts or redeploys. That is fine for a demo. For permanent data, attach a persistent disk and
point `DATABASE` at it, or move to PostgreSQL.

## Troubleshooting

**"This server can't read that file type yet because the 'pypdf' package is not installed"** (or an
older message, "Something went wrong on our side", when uploading a PDF).
The Python that runs the app does not have the libraries installed. Stop the app, then run this in the
same terminal and virtual environment you use for `python app.py`:

```bash
pip install -r requirements.txt
python -c "import flask, pypdf, docx; print('all libraries found')"
python app.py
```

If you use a virtual environment, activate it first (`venv\Scripts\activate` on Windows). When the app
starts it also prints a `Missing package(s)` warning in the terminal if anything is absent.

**"We couldn't find any known skills in that job description."** The matcher only recognises the skills in its
dictionary (software, data, cloud, AI and general CS skills). Paste a job posting that names technologies,
or add words to `SKILLS` in `matcher.py`.

**Any other "Something went wrong on our side" message.** The real reason is printed, with a full traceback,
in the terminal where `python app.py` is running. Look at the last lines there.

## Known limitations

- Scanned (image-only) PDFs cannot be read because there is no OCR. The app says so and suggests pasting the text.
- The matcher knows the skills in its dictionary (`SKILLS` in `matcher.py`, easy to extend). A skill that is not in the list is not counted.
- There is no password reset or email verification.
- Login throttling is kept in memory, so it resets when the server restarts and is per worker process.

## Explaining this project in an interview

1. **What it is:** a full-stack tracker where each student manages applications and checks resume-to-job fit.
2. **Security:** passwords are hashed, sessions are signed cookies, and every query is scoped by user ID, so one user can never reach another's records. This is tested.
3. **Matcher:** it extracts skills from the actual text with whole-word matching and aliases, then computes matched / required. Deterministic, explainable, no external API.
4. **Reliability:** all input is validated server-side with plain-language errors, global error handlers hide stack traces, and 121 automated tests cover the main rules.
5. **Trade-offs:** SQLite and a rule-based matcher keep it simple and dependency-free. The next steps would be PostgreSQL, OCR for scanned resumes, and an optional LLM "improve my resume" suggestion.
