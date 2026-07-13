from flask import Blueprint, g, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db
from . import questions as qmod
from .quiz import create_attempt, MIN_MINUTES, MAX_MINUTES

bp = Blueprint("review", __name__, url_prefix="/review")


def wrong_question_ids(db, user_id):
    """Question ids whose most recent answer by this user was wrong."""
    rows = db.execute(
        """
        SELECT aa.question_id, aa.is_correct, a.started_at
        FROM attempt_answers aa
        JOIN attempts a ON a.id = aa.attempt_id
        WHERE a.user_id = ? AND a.status != 'in_progress' AND aa.selected_position IS NOT NULL
        ORDER BY a.started_at ASC
        """,
        (user_id,),
    ).fetchall()
    latest = {}
    for r in rows:
        latest[r["question_id"]] = r["is_correct"]
    return [qid for qid, correct in latest.items() if correct == 0]


@bp.route("/")
@login_required
def form():
    db = get_db()
    available = len(wrong_question_ids(db, g.user["id"]))
    return render_template("review.html", available=available)


@bp.route("/new", methods=("POST",))
@login_required
def new_review():
    db = get_db()
    question_ids = wrong_question_ids(db, g.user["id"])
    if not question_ids:
        return redirect(url_for("review.form"))

    try:
        count = int(request.form.get("count", "0"))
    except ValueError:
        count = 0
    try:
        minutes = int(request.form.get("minutes", "0"))
    except ValueError:
        minutes = 0
    count = max(1, min(count, len(question_ids)))
    minutes = max(MIN_MINUTES, min(minutes, MAX_MINUTES))

    selected = qmod.build_quiz_from_ids(question_ids, count=count)
    attempt_id = create_attempt(db, g.user["id"], selected, minutes * 60, mode="review")
    return redirect(url_for("quiz.view_attempt", attempt_id=attempt_id))
