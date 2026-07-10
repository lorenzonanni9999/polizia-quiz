import sqlite3
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash

DEFAULT_USERNAME = "dgps"
DEFAULT_PASSWORD = "forzaalessia"
DEFAULT_QUOTA_PER_SUBJECT = 10
QUIZ_DURATION_SECONDS = 90 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subject_quota (
    subject TEXT PRIMARY KEY,
    quota INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress',
    total_questions INTEGER NOT NULL,
    correct_count INTEGER,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS attempt_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    option_order TEXT NOT NULL,
    selected_position INTEGER,
    is_correct INTEGER,
    FOREIGN KEY (attempt_id) REFERENCES attempts (id)
);

CREATE INDEX IF NOT EXISTS idx_attempt_answers_attempt
    ON attempt_answers (attempt_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user
    ON attempts (user_id);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app, subjects):
    Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.executescript(SCHEMA)

    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)",
        (DEFAULT_USERNAME, generate_password_hash(DEFAULT_PASSWORD)),
    )

    for subject in subjects:
        conn.execute(
            "INSERT OR IGNORE INTO subject_quota (subject, quota) VALUES (?, ?)",
            (subject, DEFAULT_QUOTA_PER_SUBJECT),
        )

    conn.commit()
    conn.close()


def register_db(app):
    app.teardown_appcontext(close_db)
