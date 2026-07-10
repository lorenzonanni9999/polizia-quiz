import sqlite3
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash

DEFAULT_USERNAME = "dgps"
DEFAULT_PASSWORD = "forzaalessia"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DEFAULT_QUOTA_PER_SUBJECT = 10
QUIZ_DURATION_SECONDS = 90 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0
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
    paused_at TEXT,
    paused_seconds INTEGER NOT NULL DEFAULT 0,
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


def _ensure_column(conn, table, column, coldef):
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")


def init_db(app, subjects):
    Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.executescript(SCHEMA)

    # migrations for databases created before these columns existed
    _ensure_column(conn, "users", "is_admin", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "attempts", "paused_at", "TEXT")
    _ensure_column(conn, "attempts", "paused_seconds", "INTEGER NOT NULL DEFAULT 0")

    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
        (DEFAULT_USERNAME, generate_password_hash(DEFAULT_PASSWORD)),
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
        (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)),
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
