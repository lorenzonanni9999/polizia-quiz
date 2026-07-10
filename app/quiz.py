import json
from datetime import datetime, timezone

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db, QUIZ_DURATION_SECONDS
from . import questions as qmod

bp = Blueprint("quiz", __name__, url_prefix="/quiz")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value):
    return datetime.fromisoformat(value)


def _get_owned_attempt(db, attempt_id):
    attempt = db.execute(
        "SELECT * FROM attempts WHERE id = ?", (attempt_id,)
    ).fetchone()
    if attempt is None or attempt["user_id"] != g.user["id"]:
        abort(404)
    return attempt


def _grade_and_close(db, attempt, status):
    answers = db.execute(
        "SELECT * FROM attempt_answers WHERE attempt_id = ?", (attempt["id"],)
    ).fetchall()
    correct_count = sum(1 for a in answers if a["is_correct"] == 1)
    db.execute(
        "UPDATE attempts SET status = ?, finished_at = ?, correct_count = ? WHERE id = ?",
        (status, _now_iso(), correct_count, attempt["id"]),
    )
    db.commit()


def create_attempt(db, user_id, selected, duration_seconds):
    """Persist a new attempt (and its question snapshot) and return its id."""
    cur = db.execute(
        """INSERT INTO attempts (user_id, started_at, duration_seconds, status, total_questions)
           VALUES (?, ?, ?, 'in_progress', ?)""",
        (user_id, _now_iso(), duration_seconds, len(selected)),
    )
    attempt_id = cur.lastrowid

    for position, item in enumerate(selected):
        db.execute(
            """INSERT INTO attempt_answers (attempt_id, position, question_id, subject, option_order)
               VALUES (?, ?, ?, ?, ?)""",
            (attempt_id, position, item["question_id"], item["subject"],
             json.dumps(item["option_order"])),
        )
    db.commit()
    return attempt_id


@bp.route("/new", methods=("POST",))
@login_required
def new_attempt():
    db = get_db()
    rows = db.execute("SELECT subject, quota FROM subject_quota").fetchall()
    subject_quota = {r["subject"]: r["quota"] for r in rows}

    selected = qmod.build_quiz(subject_quota)
    if not selected:
        return redirect(url_for("dashboard.settings"))

    attempt_id = create_attempt(db, g.user["id"], selected, QUIZ_DURATION_SECONDS)
    return redirect(url_for("quiz.view_attempt", attempt_id=attempt_id))


@bp.route("/<int:attempt_id>")
@login_required
def view_attempt(attempt_id):
    db = get_db()
    attempt = _get_owned_attempt(db, attempt_id)

    if attempt["status"] != "in_progress":
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    elapsed = (datetime.now(timezone.utc) - _parse_iso(attempt["started_at"])).total_seconds()
    remaining = attempt["duration_seconds"] - elapsed
    if remaining <= 0:
        _grade_and_close(db, attempt, "expired")
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    answer_rows = db.execute(
        "SELECT * FROM attempt_answers WHERE attempt_id = ? ORDER BY position",
        (attempt_id,),
    ).fetchall()

    items = []
    for row in answer_rows:
        q = qmod.get_question(row["question_id"])
        order = json.loads(row["option_order"])
        display_options = [q["options"][i] for i in order]
        items.append({
            "position": row["position"],
            "subject": row["subject"],
            "question": q["question"],
            "options": display_options,
        })

    subjects_in_order = []
    for item in items:
        if item["subject"] not in subjects_in_order:
            subjects_in_order.append(item["subject"])
    grouped = [
        {"subject": s, "questions": [it for it in items if it["subject"] == s]}
        for s in subjects_in_order
    ]

    return render_template(
        "quiz.html",
        attempt=attempt,
        grouped=grouped,
        remaining_seconds=int(remaining),
    )


@bp.route("/<int:attempt_id>/submit", methods=("POST",))
@login_required
def submit_attempt(attempt_id):
    db = get_db()
    attempt = _get_owned_attempt(db, attempt_id)

    if attempt["status"] != "in_progress":
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    elapsed = (datetime.now(timezone.utc) - _parse_iso(attempt["started_at"])).total_seconds()
    status = "expired" if elapsed > attempt["duration_seconds"] + 5 else "completed"

    answer_rows = db.execute(
        "SELECT * FROM attempt_answers WHERE attempt_id = ?", (attempt_id,)
    ).fetchall()

    for row in answer_rows:
        field = f"answer_{row['position']}"
        raw = request.form.get(field)
        selected_position = int(raw) if raw is not None and raw != "" else None
        is_correct = None
        if selected_position is not None:
            order = json.loads(row["option_order"])
            is_correct = 1 if order[selected_position] == 0 else 0
        db.execute(
            "UPDATE attempt_answers SET selected_position = ?, is_correct = ? WHERE id = ?",
            (selected_position, is_correct, row["id"]),
        )
    db.commit()

    _grade_and_close(db, attempt, status)
    return redirect(url_for("quiz.results", attempt_id=attempt_id))


@bp.route("/<int:attempt_id>/results")
@login_required
def results(attempt_id):
    db = get_db()
    attempt = _get_owned_attempt(db, attempt_id)

    if attempt["status"] == "in_progress":
        return redirect(url_for("quiz.view_attempt", attempt_id=attempt_id))

    answer_rows = db.execute(
        "SELECT * FROM attempt_answers WHERE attempt_id = ? ORDER BY position",
        (attempt_id,),
    ).fetchall()

    items = []
    subject_totals = {}
    for row in answer_rows:
        q = qmod.get_question(row["question_id"])
        order = json.loads(row["option_order"])
        display_options = [q["options"][i] for i in order]
        correct_position = order.index(0)
        items.append({
            "subject": row["subject"],
            "question": q["question"],
            "options": display_options,
            "selected_position": row["selected_position"],
            "correct_position": correct_position,
            "is_correct": row["is_correct"],
        })
        st = subject_totals.setdefault(row["subject"], {"total": 0, "correct": 0, "answered": 0})
        st["total"] += 1
        st["answered"] += 1 if row["selected_position"] is not None else 0
        st["correct"] += 1 if row["is_correct"] == 1 else 0

    subjects_in_order = []
    for item in items:
        if item["subject"] not in subjects_in_order:
            subjects_in_order.append(item["subject"])

    subject_rows = [
        {"subject": s, **subject_totals[s]} for s in subjects_in_order
    ]

    pct = round((attempt["correct_count"] or 0) / attempt["total_questions"] * 100, 1)

    return render_template(
        "results.html",
        attempt=attempt,
        items=items,
        subject_rows=subject_rows,
        pct=pct,
    )
