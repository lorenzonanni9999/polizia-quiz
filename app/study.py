import json

from flask import Blueprint, g, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db
from . import questions as qmod
from . import quiz as quizmod

bp = Blueprint("study", __name__, url_prefix="/study")


def _bookmarked_ids(db, user_id):
    return {
        r["question_id"] for r in db.execute(
            "SELECT question_id FROM bookmarks WHERE user_id = ?", (user_id,)
        ).fetchall()
    }


@bp.route("/<int:attempt_id>")
@login_required
def view_current(attempt_id):
    db = get_db()
    attempt = quizmod.get_owned_attempt(db, attempt_id)

    if attempt["status"] != "in_progress":
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    total = attempt["total_questions"]
    answered = db.execute(
        "SELECT COUNT(*) AS n FROM attempt_answers WHERE attempt_id = ? AND selected_position IS NOT NULL",
        (attempt_id,),
    ).fetchone()["n"]

    next_row = db.execute(
        """SELECT * FROM attempt_answers WHERE attempt_id = ? AND selected_position IS NULL
           ORDER BY position LIMIT 1""",
        (attempt_id,),
    ).fetchone()

    if next_row is None:
        quizmod.grade_and_close(db, attempt, "completed")
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    q = qmod.get_question(next_row["question_id"])
    order = json.loads(next_row["option_order"])
    display_options = [q["options"][i] for i in order]
    bookmarked = next_row["question_id"] in _bookmarked_ids(db, g.user["id"])

    return render_template(
        "study_question.html",
        attempt=attempt,
        position=next_row["position"],
        question_id=next_row["question_id"],
        question=q["question"],
        subject=next_row["subject"],
        options=display_options,
        answered=answered,
        total=total,
        is_bookmarked=bookmarked,
    )


@bp.route("/<int:attempt_id>/answer", methods=("POST",))
@login_required
def answer(attempt_id):
    db = get_db()
    attempt = quizmod.get_owned_attempt(db, attempt_id)

    if attempt["status"] != "in_progress":
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    position = request.form.get("position", type=int)
    row = db.execute(
        "SELECT * FROM attempt_answers WHERE attempt_id = ? AND position = ?",
        (attempt_id, position),
    ).fetchone()
    if row is None:
        return redirect(url_for("study.view_current", attempt_id=attempt_id))

    raw = request.form.get("answer")
    selected_position = int(raw) if raw not in (None, "") else None
    order = json.loads(row["option_order"])
    is_correct = None
    if selected_position is not None:
        is_correct = 1 if order[selected_position] == 0 else 0
        db.execute(
            "UPDATE attempt_answers SET selected_position = ?, is_correct = ? WHERE id = ?",
            (selected_position, is_correct, row["id"]),
        )
        db.commit()

    q = qmod.get_question(row["question_id"])
    display_options = [q["options"][i] for i in order]
    correct_position = order.index(0)
    answered = db.execute(
        "SELECT COUNT(*) AS n FROM attempt_answers WHERE attempt_id = ? AND selected_position IS NOT NULL",
        (attempt_id,),
    ).fetchone()["n"]
    bookmarked = row["question_id"] in _bookmarked_ids(db, g.user["id"])

    return render_template(
        "study_feedback.html",
        attempt=attempt,
        question=q["question"],
        subject=row["subject"],
        options=display_options,
        selected_position=selected_position,
        correct_position=correct_position,
        is_correct=is_correct,
        answered=answered,
        total=attempt["total_questions"],
        question_id=row["question_id"],
        is_bookmarked=bookmarked,
    )
